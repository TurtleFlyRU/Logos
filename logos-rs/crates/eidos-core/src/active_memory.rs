//! Пассивный блок «Активное извлечение из памяти» без Python sidecar.

use std::time::{SystemTime, UNIX_EPOCH};

use regex::Regex;
use crate::episodic_store::EpisodicStore;
use crate::error::Result;
use crate::journal_search::search_journal_lexical;
use crate::ml_client::{search_external_hits, search_journal_hits};
use crate::paths::Paths;
use crate::semantic_store::SemanticStore;
use crate::working_memory::WorkingMemory;
use eidos_protocol::episodic::EpisodicEpisode;
use eidos_protocol::semantic::SemanticPrinciple;

struct PipelineModes {
    name: &'static str,
    episodic: bool,
    semantic_lexical: bool,
    journal_semantic: bool,
    journal_lexical: bool,
    external_semantic: bool,
}

pub fn use_rust_active_memory() -> bool {
    let force = env_on("EIDOS_RUST_ACTIVE_MEMORY", false);
    force || crate::py_sidecar::env_no_sidecar()
}

pub fn format_active_memory_block(
    paths: &Paths,
    wm: &WorkingMemory,
    persona: &str,
    cli_session_id: &str,
    user_message: &str,
    max_chars: usize,
) -> Result<String> {
    if max_chars == 0 {
        return Ok(String::new());
    }
    let pm = pipeline_modes();
    let wm_tail = wm_tail_plain(wm, cli_session_id);
    let mut cues = merged_cues(user_message, &wm_tail);
    augment_cues_with_user(wm, persona, &mut cues);

    let now = now_ts();
    let recent_n = active_recent_n();
    let kw_top = active_keyword_top();
    let budget_total = max_chars;
    let mut budget_remaining = budget_total;
    let mut lines_out = String::new();

    let cap_label = episodic_scan_cap()
        .map(|c| format!("cap={c}"))
        .unwrap_or_else(|| "без искусственного LIMIT «последние N»".to_string());
    emit(
        &mut lines_out,
        &mut budget_remaining,
        &format!(
            "— Активное извлечение из памяти (pipeline={name}; эпизодический скан {cap_label}, backend=rust):\n",
            name = pm.name,
        ),
    );
    if budget_remaining == 0 {
        return Ok(lines_out);
    }

    if pm.episodic {
        emit_episodic(
            paths,
            &pm,
            &cues,
            user_message,
            now,
            recent_n,
            kw_top,
            &mut lines_out,
            &mut budget_remaining,
            budget_total,
        )?;
    }
    if budget_remaining == 0 {
        return Ok(trim_block(lines_out));
    }

    if pm.semantic_lexical {
        emit_semantic(paths, &cues, kw_top, &mut lines_out, &mut budget_remaining)?;
    }
    if budget_remaining == 0 {
        return Ok(trim_block(lines_out));
    }

    let mut journal_q = user_message.trim().to_string();
    if journal_q.is_empty() {
        journal_q = " ".to_string();
    }
    if is_identity_question(user_message) && !wm_tail.is_empty() {
        let tail = wm_tail.chars().rev().take(900).collect::<String>();
        let tail: String = tail.chars().rev().collect();
        journal_q = format!("{user_message}\n{tail}");
        if journal_q.len() > 2500 {
            journal_q.truncate(2500);
        }
    }

    if pm.journal_semantic {
        let hits = search_journal_hits(paths, &journal_q, 10)?;
        if !hits.is_empty() {
            emit(
                &mut lines_out,
                &mut budget_remaining,
                "  · Дневник (семантический поиск, eidos-ml или лексика):\n",
            );
            for h in &hits {
                let file = h.get("file").and_then(|v| v.as_str()).unwrap_or("?");
                let snippet = h
                    .get("snippet")
                    .or_else(|| h.get("section"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                emit(
                    &mut lines_out,
                    &mut budget_remaining,
                    &format!("    [{file}] {}\n", truncate(snippet, 300)),
                );
                if budget_remaining == 0 {
                    break;
                }
            }
        }
    } else if pm.journal_lexical {
        let hits = search_journal_lexical(paths, &journal_q, 12)?;
        if !hits.is_empty() {
            emit(
                &mut lines_out,
                &mut budget_remaining,
                "  · Дневник (лексический поиск по строкам):\n",
            );
            for h in &hits {
                let sec = if h.section.is_empty() {
                    String::new()
                } else {
                    format!(" — {}", h.section)
                };
                emit(
                    &mut lines_out,
                    &mut budget_remaining,
                    &format!(
                        "    [{}]{} {}\n",
                        h.file,
                        sec,
                        truncate(&h.snippet, 300)
                    ),
                );
                if budget_remaining == 0 {
                    break;
                }
            }
        }
    }

    if budget_remaining == 0 {
        return Ok(trim_block(lines_out));
    }

    let mut ext_q = user_message.trim().to_string();
    if is_identity_question(user_message) && !wm_tail.is_empty() {
        let tail: String = wm_tail.chars().rev().take(600).collect::<String>();
        let tail: String = tail.chars().rev().collect();
        ext_q = format!("{user_message}\n{tail}");
        if ext_q.len() > 2000 {
            ext_q.truncate(2000);
        }
    }
    if pm.external_semantic && !ext_q.is_empty() {
        let resp = search_external_hits(paths, &ext_q, 8, 0.12)?;
        let hits = resp
            .get("hits")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        if !hits.is_empty() {
            let backend = resp
                .get("backend")
                .and_then(|v| v.as_str())
                .unwrap_or("?");
            emit(
                &mut lines_out,
                &mut budget_remaining,
                &format!("  · Внешняя память ({backend}):\n"),
            );
            for h in hits {
                let title = h
                    .get("title")
                    .or_else(|| h.get("source"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let sn = h.get("snippet").and_then(|v| v.as_str()).unwrap_or("");
                emit(
                    &mut lines_out,
                    &mut budget_remaining,
                    &format!("    [{title}] {}\n", truncate(sn, 360)),
                );
                if budget_remaining == 0 {
                    break;
                }
            }
        }
    }

    Ok(trim_block(lines_out))
}

fn emit_episodic(
    paths: &Paths,
    _pm: &PipelineModes,
    cues: &[String],
    user_message: &str,
    now: f64,
    recent_n: usize,
    kw_top: usize,
    lines_out: &mut String,
    budget_remaining: &mut usize,
    budget_total: usize,
) -> Result<()> {
    let store = EpisodicStore::open(paths)?;
    let cap = episodic_scan_cap().unwrap_or(5000);
    let pool = store.query(cap, 0.0)?;
    if pool.is_empty() {
        emit(lines_out, budget_remaining, "  · Эпизодическая память: пусто или недоступна.\n");
        return Ok(());
    }

    let mut by_ts = pool;
    by_ts.sort_by(|a, b| {
        b.timestamp
            .partial_cmp(&a.timestamp)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let recent: Vec<&EpisodicEpisode> = by_ts.iter().take(recent_n).collect();

    let mut keyword_eps: Vec<&EpisodicEpisode> = Vec::new();
    if !cues.is_empty() && kw_top > 0 {
        let mut scored: Vec<(f64, &EpisodicEpisode)> = by_ts
            .iter()
            .map(|ep| (score_episode_for_cues(ep, cues, now), ep))
            .collect();
        scored.sort_by(|a, b| {
            b.0.partial_cmp(&a.0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    b.1.timestamp
                        .partial_cmp(&a.1.timestamp)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
        });
        keyword_eps = scored
            .into_iter()
            .filter(|(s, _)| *s > 0.0)
            .take(kw_top)
            .map(|(_, ep)| ep)
            .collect();
    }

    let mut identity_eps: Vec<&EpisodicEpisode> = Vec::new();
    if kw_top > 0 && is_identity_question(user_message) {
        let i_take = 12_usize.max(kw_top);
        let mut scored_i: Vec<(&EpisodicEpisode, f64)> = by_ts
            .iter()
            .map(|ep| (ep, score_identity_probe(ep, now)))
            .collect();
        scored_i.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        identity_eps = scored_i
            .into_iter()
            .filter(|(_, s)| *s > 0.0)
            .take(i_take)
            .map(|(ep, _)| ep)
            .collect();
    }

    let mut merged: Vec<&EpisodicEpisode> = Vec::new();
    let mut seen: std::collections::HashSet<i64> = std::collections::HashSet::new();
    for ep in recent
        .into_iter()
        .chain(keyword_eps.into_iter())
        .chain(identity_eps.into_iter())
    {
        let key = ep.id.unwrap_or(-1);
        if seen.insert(key) {
            merged.push(ep);
        }
    }

    emit(
        lines_out,
        budget_remaining,
        &format!(
            "  · Эпизодическая память ({} записей в выборке; в блок — до лимита):\n",
            by_ts.len()
        ),
    );
    for ep in merged {
        let date_str = format_timestamp(ep.timestamp);
        let body = if !ep.raw_text.trim().is_empty() {
            ep.raw_text.trim()
        } else {
            ep.summary.trim()
        };
        let body = body.replace('\n', " ");
        let eid = ep.id.map(|i| i.to_string()).unwrap_or_else(|| "?".into());
        let line = format!(
            "    [{date_str}] id={eid} | {}\n",
            truncate(&body, 520)
        );
        emit(lines_out, budget_remaining, &line);
        if *budget_remaining == 0 {
            emit(
                lines_out,
                budget_remaining,
                &format!("    … (обрезано по бюджету {budget_total} символов)\n"),
            );
            break;
        }
    }
    Ok(())
}

fn emit_semantic(
    paths: &Paths,
    cues: &[String],
    kw_top: usize,
    lines_out: &mut String,
    budget_remaining: &mut usize,
) -> Result<()> {
    let store = SemanticStore::open(paths)?;
    let mut rows = store.get_principles(0.0, 500)?;
    if rows.is_empty() {
        return Ok(());
    }
    rows.sort_by(|a, b| {
        score_principle(b, cues)
            .partial_cmp(&score_principle(a, cues))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                b.confidence
                    .partial_cmp(&a.confidence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });
    let take = if cues.is_empty() {
        8
    } else {
        (8).max(kw_top + 4)
    };
    rows.truncate(take);
    emit(
        lines_out,
        budget_remaining,
        "  · Семантическая память (принципы, скоринг по реплике):\n",
    );
    for row in rows {
        let p = row.principle.replace('\n', " ");
        emit(
            lines_out,
            budget_remaining,
            &format!(
                "    id={} [{:.2}] {}\n",
                row.id.map(|i| i.to_string()).unwrap_or_else(|| "?".into()),
                row.confidence,
                truncate(&p, 420)
            ),
        );
        if *budget_remaining == 0 {
            break;
        }
    }
    Ok(())
}

fn score_episode_for_cues(ep: &EpisodicEpisode, cues: &[String], now: f64) -> f64 {
    let blob = format!("{}\n{}", ep.summary, ep.raw_text).to_lowercase();
    let hits: usize = cues.iter().map(|c| blob.matches(c.as_str()).count()).sum();
    let age = (now - ep.timestamp).max(0.0);
    let recency = 1.0 / (1.0 + age / 86400.0);
    hits as f64 * 18.0 + ep.salience as f64 * 0.55 + recency * 3.0
}

fn episode_identity_hint_score(ep: &EpisodicEpisode) -> f64 {
    let blob = format!("{}\n{}", ep.summary, ep.raw_text).to_lowercase();
    let mut score = 0.0;
    for kw in ["имя", "зовут", "пользователь", "user", "display_name", "turtlefly"] {
        if blob.contains(kw) {
            score += 1.0;
        }
    }
    score
}

fn score_identity_probe(ep: &EpisodicEpisode, now: f64) -> f64 {
    let hint = episode_identity_hint_score(ep);
    let age = (now - ep.timestamp).max(0.0);
    let recency = 1.0 / (1.0 + age / 86400.0);
    hint * 15.0 + recency * 4.0 + ep.salience as f64 * 0.45
}

fn score_principle(row: &SemanticPrinciple, cues: &[String]) -> f64 {
    let text = row.principle.to_lowercase();
    let hits: usize = cues.iter().map(|c| text.matches(c.as_str()).count()).sum();
    hits as f64 * 14.0 + row.confidence as f64 * 2.0
}

fn wm_tail_plain(wm: &WorkingMemory, cli_session_id: &str) -> String {
    let mut parts: Vec<String> = Vec::new();
    let mut count = 0usize;
    for ev in wm.document().events.iter().rev() {
        if ev.cli_session_id.as_deref() != Some(cli_session_id) {
            continue;
        }
        let role = ev.role.as_deref().unwrap_or("");
        if role != "user" && role != "assistant" {
            continue;
        }
        if let Some(t) = ev.text_content() {
            let s = t.trim();
            if !s.is_empty() {
                parts.push(s.to_string());
            }
        }
        count += 1;
        if count >= 44 {
            break;
        }
    }
    parts.reverse();
    parts.join("\n")
}

fn merged_cues(user_message: &str, wm_tail: &str) -> Vec<String> {
    let mut out = cue_tokens(user_message);
    let seen: std::collections::HashSet<String> = out.iter().cloned().collect();
    for t in cue_tokens(wm_tail) {
        if out.len() >= 36 {
            break;
        }
        if !seen.contains(&t) {
            out.push(t);
        }
    }
    out
}

fn augment_cues_with_user(wm: &WorkingMemory, persona: &str, cues: &mut Vec<String>) {
    let name = resolve_user_display_name(wm, persona);
    if name.is_empty() {
        return;
    }
    let lowered = name.to_lowercase();
    let mut seen: std::collections::HashSet<String> = cues.iter().cloned().collect();
    if !seen.contains(&lowered) && cues.len() < 56 {
        cues.push(lowered.clone());
        seen.insert(lowered.clone());
    }
    for tok in cue_tokens(&lowered) {
        if cues.len() >= 56 {
            break;
        }
        if seen.insert(tok.clone()) {
            cues.push(tok);
        }
    }
}

fn resolve_user_display_name(wm: &WorkingMemory, persona: &str) -> String {
    if let Some(n) = wm.document().context.user_display_name.as_ref() {
        let s = n.trim();
        if !s.is_empty() {
            return s.to_string();
        }
    }
    identity_from_persona(persona).unwrap_or_default()
}

fn identity_from_persona(persona: &str) -> Option<String> {
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(r"\((?:[^,)]{2,64}),\s*([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{1,48})\)")
            .expect("persona identity regex")
    });
    re.captures(persona)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().trim().to_string())
        .filter(|s| !s.is_empty())
}

fn is_identity_question(text: &str) -> bool {
    let s = text.trim();
    if s.len() > 160 {
        return false;
    }
    static RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(
            r"(?i)(^|\b)(кто\s+я|кто\s+тут|как\s+(меня\s+)?зовут|мо[ёе]\s+имя|who\s+am\s+i|what'?s\s+my\s+name)(\b|$)",
        )
        .expect("identity question regex")
    });
    re.is_match(s)
}

fn cue_tokens(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut cur = String::new();
    for ch in text.to_lowercase().chars() {
        if ch.is_alphanumeric() || ch == '_' || ('\u{0400}'..='\u{04FF}').contains(&ch) {
            cur.push(ch);
        } else if !cur.is_empty() {
            if cur.len() >= 3 {
                out.push(cur.clone());
            }
            cur.clear();
        }
    }
    if cur.len() >= 3 {
        out.push(cur);
    }
    out
}

fn pipeline_modes() -> PipelineModes {
    let name = std::env::var("EIDOS_CHAT_MEMORY_PIPELINE")
        .unwrap_or_else(|_| "full".into())
        .to_ascii_lowercase();
    match name.as_str() {
        "lexical" => PipelineModes {
            name: "lexical",
            episodic: true,
            semantic_lexical: true,
            journal_semantic: false,
            journal_lexical: true,
            external_semantic: false,
        },
        "episodic_only" => PipelineModes {
            name: "episodic_only",
            episodic: true,
            semantic_lexical: false,
            journal_semantic: false,
            journal_lexical: false,
            external_semantic: false,
        },
        _ => PipelineModes {
            name: "full",
            episodic: true,
            semantic_lexical: true,
            journal_semantic: true,
            journal_lexical: false,
            external_semantic: true,
        },
    }
}

fn env_on(name: &str, default: bool) -> bool {
    let raw = std::env::var(name).unwrap_or_default();
    let raw = raw.trim().to_ascii_lowercase();
    if raw.is_empty() {
        return default;
    }
    matches!(raw.as_str(), "1" | "true" | "yes" | "on")
}

fn active_recent_n() -> usize {
    std::env::var("EIDOS_CHAT_ACTIVE_RECENT")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .map(|n: usize| n.clamp(1, 40))
        .unwrap_or(8)
}

fn active_keyword_top() -> usize {
    std::env::var("EIDOS_CHAT_ACTIVE_KEYWORD_TOP")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .map(|n: usize| n.clamp(0, 40))
        .unwrap_or(12)
}

fn episodic_scan_cap() -> Option<usize> {
    let raw = std::env::var("EIDOS_CHAT_EPISODIC_SCAN_CAP").unwrap_or_default();
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    raw.parse::<usize>().ok().filter(|&v| v > 0).map(|v| v.min(2_000_000))
}

fn emit(out: &mut String, rem: &mut usize, line: &str) {
    if *rem == 0 {
        return;
    }
    let take = line.len().min(*rem);
    if take > 0 {
        out.push_str(&line[..take]);
        *rem -= take;
    }
}

fn trim_block(mut s: String) -> String {
    while s.ends_with('\n') {
        s.pop();
    }
    s.push('\n');
    s
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}…", &s[..max.saturating_sub(1)])
    }
}

fn format_timestamp(ts: f64) -> String {
    let secs = ts.max(0.0) as i64;
    let h = (secs % 86400) / 3600;
    let m = (secs % 3600) / 60;
    let days = secs / 86400;
    format!("day+{days} {h:02}:{m:02}")
}

fn now_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}
