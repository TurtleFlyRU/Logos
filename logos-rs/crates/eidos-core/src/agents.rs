//! Загрузка agents.yaml и параметров LLM (аналог `cli/agent_backends.py`).

use std::env;
use std::fs;
use eidos_protocol::agents::{AgentProfile, AgentsConfig};

use crate::error::{CoreError, Result};
use crate::paths::Paths;

const DEFAULT_BASE_URL: &str = "https://api.deepseek.com/v1";
const DEFAULT_MODEL: &str = "deepseek-chat";

/// Параметры одного запроса chat/completions.
#[derive(Debug, Clone)]
pub struct LlmRuntimeParams {
    pub api_key: String,
    pub base_url: String,
    pub model: String,
    pub read_timeout_sec: f64,
    pub omit_authorization_header: bool,
    pub profile_name: String,
}

fn effective_read_timeout(default_sec: f64) -> f64 {
    if let Ok(raw) = env::var("LLM_TIMEOUT_SEC") {
        if let Ok(v) = raw.trim().parse::<f64>() {
            return v.max(5.0);
        }
    }
    default_sec.max(5.0)
}

fn http_trust_env() -> bool {
    let v = env::var("LLM_IGNORE_PROXY")
        .unwrap_or_default()
        .to_ascii_lowercase();
    !matches!(v.as_str(), "1" | "true" | "yes" | "on")
}

/// Нужно ли подхватывать системный прокси для reqwest.
#[must_use]
pub fn http_use_proxy() -> bool {
    http_trust_env()
}

pub fn load_agents_config(paths: &Paths) -> Result<Option<(std::path::PathBuf, AgentsConfig)>> {
    let Some(cfg_path) = paths.find_agents_config() else {
        return Ok(None);
    };
    let text = fs::read_to_string(&cfg_path)?;
    let doc: AgentsConfig = serde_yaml::from_str(&text)?;
    Ok(Some((cfg_path, doc)))
}

pub fn resolve_profile_yaml(paths: &Paths, profile_name: &str) -> Result<LlmRuntimeParams> {
    let name = profile_name.trim();
    if name.is_empty() {
        return Err(CoreError::LlmConfig("пустое имя профиля".into()));
    }
    let Some((cfg_path, doc)) = load_agents_config(paths)? else {
        return Err(CoreError::LlmConfig(
            "задан EIDOS_AGENT_PROFILE, но не найден agents.yaml".into(),
        ));
    };
    let block = doc.profiles.get(name).ok_or_else(|| {
        let avail = doc
            .profiles
            .keys()
            .cloned()
            .collect::<Vec<_>>()
            .join(", ");
        CoreError::LlmConfig(format!(
            "профиль {name:?} не описан в {}. Доступные: {avail}",
            cfg_path.display()
        ))
    })?;
    runtime_from_profile_block(name, block)
}

fn runtime_from_profile_block(name: &str, block: &AgentProfile) -> Result<LlmRuntimeParams> {
    let base = block.base_url.trim().trim_end_matches('/').to_string();
    let base = if base.is_empty() {
        DEFAULT_BASE_URL.to_string()
    } else {
        base
    };
    let model = block.model.trim();
    let model = if model.is_empty() {
        DEFAULT_MODEL.to_string()
    } else {
        model.to_string()
    };

    let mut api_key = String::new();
    if let Some(primary) = block.api_key_env.as_deref() {
        if let Ok(v) = env::var(primary) {
            api_key = v.trim().to_string();
        }
    }
    if api_key.is_empty() {
        for var in &block.api_key_fallback_envs {
            if let Ok(v) = env::var(var) {
                let t = v.trim();
                if !t.is_empty() {
                    api_key = t.to_string();
                    break;
                }
            }
        }
    }

    if !block.omit_authorization_header && api_key.is_empty() {
        return Err(CoreError::LlmConfig(format!(
            "для профиля {name:?} задайте API key в env или omit_authorization_header"
        )));
    }

    Ok(LlmRuntimeParams {
        api_key,
        base_url: base,
        model,
        read_timeout_sec: effective_read_timeout(block.read_timeout_sec),
        omit_authorization_header: block.omit_authorization_header,
        profile_name: name.to_string(),
    })
}

fn llm_host_label(base_url: &str) -> String {
    base_url
        .trim_end_matches('/')
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .split('/')
        .next()
        .unwrap_or(base_url)
        .to_string()
}

/// Строка перед HTTP (parity с ``cli.llm.format_llm_pending_banner``).
#[must_use]
pub fn format_llm_pending_banner(params: &LlmRuntimeParams) -> String {
    let host = llm_host_label(&params.base_url);
    let proxy = if http_use_proxy() { "да" } else { "нет" };
    let prof = if params.profile_name.is_empty() {
        String::new()
    } else {
        format!(" · профиль {}", params.profile_name)
    };
    format!(
        "[eidos] LLM {host}{prof} · модель {} · таймаут чтения {:.0} с · прокси из env: {proxy}",
        params.model, params.read_timeout_sec
    )
}

/// Краткий баннер (legacy).
#[must_use]
pub fn format_llm_banner(params: &LlmRuntimeParams) -> String {
    format_llm_pending_banner(params)
}

pub fn get_llm_runtime_params(
    paths: &Paths,
    profile_name: Option<&str>,
) -> Result<LlmRuntimeParams> {
    let explicit = profile_name
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| {
            env::var("EIDOS_AGENT_PROFILE")
                .ok()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        });

    if let Some(ref pname) = explicit {
        return resolve_profile_yaml(paths, pname);
    }

    if let Ok(Some((_, doc))) = load_agents_config(paths) {
        let default_name = doc
            .default_profile
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| {
                doc.profiles
                    .contains_key("deepseek")
                    .then(|| "deepseek".to_string())
            });
        if let Some(ref name) = default_name {
            return resolve_profile_yaml(paths, name);
        }
    }

    let api_key = env::var("LLM_API_KEY")
        .or_else(|_| env::var("DEEPSEEK_API_KEY"))
        .unwrap_or_default()
        .trim()
        .to_string();
    let base = env::var("LLM_BASE_URL")
        .unwrap_or_else(|_| DEFAULT_BASE_URL.to_string())
        .trim()
        .trim_end_matches('/')
        .to_string();
    let base = if base.is_empty() {
        DEFAULT_BASE_URL.to_string()
    } else {
        base
    };
    let model = env::var("LLM_MODEL")
        .unwrap_or_else(|_| DEFAULT_MODEL.to_string())
        .trim()
        .to_string();
    let model = if model.is_empty() {
        DEFAULT_MODEL.to_string()
    } else {
        model
    };

    if api_key.is_empty() {
        return Err(CoreError::LlmConfig(
            "задайте DEEPSEEK_API_KEY или LLM_API_KEY (файл .env в корне репозитория)".into(),
        ));
    }

    Ok(LlmRuntimeParams {
        api_key,
        base_url: base,
        model,
        read_timeout_sec: effective_read_timeout(120.0),
        omit_authorization_header: false,
        profile_name: String::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_local_profile_if_config_exists() {
        let paths = crate::paths::resolve_paths().expect("paths");
        if paths.find_agents_config().is_none() {
            return;
        }
        let params = resolve_profile_yaml(&paths, "openai_compatible_local");
        if params.is_ok() {
            let p = params.unwrap();
            assert!(p.base_url.contains("http"));
            assert!(p.omit_authorization_header);
        }
    }
}
