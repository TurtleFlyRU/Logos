"""Точка входа CLI: подкоманды chat, ask, boot, sleep, import-opencode, run, review."""

from __future__ import annotations

import argparse
import os
import sys


def _maybe_set_agent_profile_from_args(args: argparse.Namespace) -> None:
    """Если задан ``--agent-profile``, выставить ``EIDOS_AGENT_PROFILE`` для процесса."""
    ap = getattr(args, "agent_profile", None)
    if isinstance(ap, str) and ap.strip():
        os.environ["EIDOS_AGENT_PROFILE"] = ap.strip()


def _cmd_chat(args: argparse.Namespace) -> int:
    from kernel.memory import Memory

    from cli import session as sess
    from cli.identity import seed_user_display_name_from_agents_md
    from cli.runtime import run_chat_interactive

    _maybe_set_agent_profile_from_args(args)

    if getattr(args, "session", None) and args.new:
        print("Нельзя использовать --session и --new вместе.", file=sys.stderr)
        return 2

    memory = Memory(auto_boot=False)

    if args.session:
        if not sess.is_uuid(args.session):
            print("Аргумент --session должен быть UUID.", file=sys.stderr)
            return 2
        sid = sess.normalize_session_id(args.session)
        sess.touch_session(sid)
        memory.working.set_context("cli_session_id", sid)
        memory.working.set_context("cli_transport", "eidos")
        sess.write_latest(sid)
    elif args.new:
        sid = sess.new_session_id()
        memory.working.clear()
        memory.working.set_context("cli_session_id", sid)
        memory.working.set_context("cli_transport", "eidos")
        sess.touch_session(sid)
        sess.write_latest(sid)
    else:
        latest = sess.read_latest()
        sid = latest if latest else sess.new_session_id()
        sess.touch_session(sid)
        memory.working.set_context("cli_session_id", sid)
        memory.working.set_context("cli_transport", "eidos")
        sess.write_latest(sid)

    # OpenCode-подобное поведение: имя пользователя доступно сразу, если оно зафиксировано в AGENTS.md
    seed_user_display_name_from_agents_md(memory)

    if not getattr(args, "no_boot", False):
        try:
            from kernel.boot import run_cli_chat_boot

            run_cli_chat_boot(memory)
        except Exception as exc:
            print(f"[eidos] Boot не выполнен: {exc}", flush=True)

    show_metrics = bool(getattr(args, "metrics", False)) or (
        os.environ.get("EIDOS_CHAT_METRICS", "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    run_chat_interactive(
        memory,
        sid,
        use_llm=not args.stub,
        stub=args.stub,
        show_metrics=show_metrics,
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from cli.pipelines.runner import run_pipeline_cli

    _maybe_set_agent_profile_from_args(args)
    return run_pipeline_cli(args)


def _cmd_review(args: argparse.Namespace) -> int:
    from cli.pipelines.runner import run_pipeline_cli

    _maybe_set_agent_profile_from_args(args)
    paths_flat = getattr(args, "paths", None)
    plist = list(paths_flat) if paths_flat else []
    fake = argparse.Namespace(
        pipeline="code_review",
        topic=list(getattr(args, "topic", None) or []),
        prompt=str(getattr(args, "prompt", "") or ""),
        paths=plist,
        stub=bool(getattr(args, "stub", False)),
        no_boot=bool(getattr(args, "no_boot", False)),
    )
    return run_pipeline_cli(fake)


def _cmd_ask(args: argparse.Namespace) -> int:
    from cli.runtime import run_ask

    q = " ".join(args.question).strip()
    if not q:
        print("Передайте текст вопроса.", file=sys.stderr)
        return 1
    return run_ask(q, use_llm=not args.stub)


def _cmd_boot(args: argparse.Namespace) -> int:
    from kernel.memory import Memory

    memory = Memory(auto_boot=False)
    sync_oc = getattr(args, "sync_opencode", False)
    text = memory.boot(sync_opencode=sync_oc if sync_oc else None)
    print(text)
    return 0


def _cmd_sleep(args: argparse.Namespace) -> int:
    from kernel.memory import Memory

    memory = Memory(auto_boot=False)
    report = memory.sleep(force=args.force)
    print(report)
    return 0 if report.get("status") != "skipped" else 0


def _cmd_import_opencode(args: argparse.Namespace) -> int:
    from kernel.memory import Memory

    memory = Memory(auto_boot=False)
    try:
        if args.all:
            stats = memory.import_opencode_sessions(
                all_sessions=True,
                max_sessions=args.max_sessions,
            )
            total = int(stats.pop("_total", 0))
            print(f"Импортировано новых сообщений: {total}")
            for slug, n in sorted(stats.items()):
                print(f"  {slug}: {n}")
        else:
            n = memory.import_opencode_last_session()
            print(f"Импортировано из последней сессии OpenCode: {n} новых сообщений")
    except Exception as exc:
        print(f"Импорт не выполнен: {exc}", file=sys.stderr)
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eidos",
        description="Эйдос — CLI поверх kernel/",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_chat = sub.add_parser("chat", help="Интерактивный диалог (WM + LLM)")
    p_chat.add_argument(
        "--new",
        action="store_true",
        help="Новая сессия: очистить рабочую память и выдать новый session_id",
    )
    p_chat.add_argument(
        "--session",
        metavar="UUID",
        help="Продолжить указанную сессию (создаёт JSON при отсутствии файла)",
    )
    p_chat.add_argument(
        "--stub",
        action="store_true",
        help="Не вызывать LLM (локальный echo)",
    )
    p_chat.add_argument(
        "--no-boot",
        action="store_true",
        help="Не запускать boot-ритуал при входе в chat (отладка/быстрый старт)",
    )
    p_chat.add_argument(
        "--metrics",
        action="store_true",
        help="Печатать метрики сборки контекста (budget/payload/layers) перед вызовом LLM",
    )
    p_chat.add_argument(
        "--agent-profile",
        metavar="NAME",
        help=(
            "Имя профиля LLM из agents.yaml (см. config/agents.defaults.yaml); "
            "эквивалентно export EIDOS_AGENT_PROFILE=NAME"
        ),
    )
    p_chat.set_defaults(func=_cmd_chat)

    p_ask = sub.add_parser("ask", help="Один вопрос к LLM")
    p_ask.add_argument(
        "question",
        nargs="+",
        help="Текст запроса",
    )
    p_ask.add_argument(
        "--stub",
        action="store_true",
        help="Не вызывать API, только echo",
    )
    p_ask.set_defaults(func=_cmd_ask)

    p_boot = sub.add_parser("boot", help="Вывести boot-контекст")
    p_boot.add_argument(
        "--sync-opencode",
        action="store_true",
        help="Подтянуть OpenCode в episodic и в текст boot (иначе только если задан EIDOS_SYNC_OPENCODE)",
    )
    p_boot.set_defaults(func=_cmd_boot)

    p_sleep = sub.add_parser("sleep", help="Запустить sleep-пайплайн памяти")
    p_sleep.add_argument(
        "--force",
        action="store_true",
        help="Игнорировать lock-файл",
    )
    p_sleep.set_defaults(func=_cmd_sleep)

    p_im = sub.add_parser(
        "import-opencode",
        help="Импорт истории OpenCode в episodic (явная операция; БД OpenCode не нужна для обычного boot)",
    )
    p_im.add_argument(
        "--all",
        action="store_true",
        help="Обойти несколько последних сессий (см. --max-sessions)",
    )
    p_im.add_argument(
        "--max-sessions",
        type=int,
        default=100,
        metavar="N",
        help="Максимум сессий при --all (по умолчанию 100)",
    )
    p_im.set_defaults(func=_cmd_import_opencode)

    from cli.pipelines.registry import describe_pipeline, list_pipeline_names

    names = list_pipeline_names()
    _stub_help = "Не вызывать LLM (вывести локальную заглушку с фрагментом промпта)."
    _no_boot_pipeline_help = "Не запускать boot-ритуал перед пайплайном."
    _agent_profile_pipeline_help = (
        "Профиль LLM для этапов без переопределения; для code_review см. "
        "EIDOS_CODE_REVIEW_PROFILES."
    )
    epilog_lines = [
        "Пайплайны:",
        *(f"  {n} — {describe_pipeline(n)}" for n in names),
        "",
        "Порядок аргументов: сначала опции (--stub, --paths …), затем имя пайплайна и тема.",
        "Либо задайте текст флагом -m/--prompt (удобно между опциями и темой).",
        "Файлы: повторяйте --paths для каждого пути (не используйте nargs «список через пробел»).",
    ]
    p_run = sub.add_parser(
        "run",
        help="Именованный пайплайн (контекст-пресет + один или несколько вызовов LLM)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(epilog_lines),
    )
    p_run.add_argument(
        "--paths",
        action="append",
        default=[],
        metavar="REL",
        help=(
            "Для code_review: один относительный путь под корнем репозитория "
            "(повторите ключ для нескольких файлов)."
        ),
    )
    p_run.add_argument("--stub", action="store_true", help=_stub_help)
    p_run.add_argument("--no-boot", action="store_true", help=_no_boot_pipeline_help)
    p_run.add_argument(
        "--agent-profile",
        metavar="NAME",
        help=_agent_profile_pipeline_help,
    )
    p_run.add_argument(
        "--prompt",
        "-m",
        default="",
        metavar="TEXT",
        help="Текст задачи; альтернатива позиционной теме в конце команды.",
    )
    p_run.add_argument(
        "pipeline",
        choices=list(names),
        help="Имя пайплайна",
    )
    p_run.add_argument(
        "topic",
        nargs="*",
        help="Тема в конце командной строки (после имени пайплайна), если не задана -m/--prompt",
    )
    p_run.set_defaults(func=_cmd_run)

    p_review = sub.add_parser(
        "review",
        help="Сокращение для «run code_review» (ревью кода или текста)",
    )
    p_review.add_argument(
        "--paths",
        action="append",
        default=[],
        metavar="REL",
        help="Путь к файлу в репозитории (повторите для нескольких файлов)",
    )
    p_review.add_argument(
        "--prompt",
        "-m",
        default="",
        metavar="TEXT",
        help="Формулировка задачи (если не задаёте позиционный текст в конце)",
    )
    p_review.add_argument(
        "topic",
        nargs="*",
        help="Формулировка задачи в конце (после опций)",
    )
    p_review.add_argument("--stub", action="store_true", help=_stub_help)
    p_review.add_argument("--no-boot", action="store_true", help=_no_boot_pipeline_help)
    p_review.add_argument(
        "--agent-profile",
        metavar="NAME",
        help=_agent_profile_pipeline_help,
    )
    p_review.set_defaults(func=_cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
