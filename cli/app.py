"""Точка входа CLI: подкоманды chat, ask, boot, sleep, import-opencode."""

from __future__ import annotations

import argparse
import sys


def _cmd_chat(args: argparse.Namespace) -> int:
    from kernel.memory import Memory

    from cli import session as sess
    from cli.identity import seed_user_display_name_from_agents_md
    from cli.runtime import run_chat_interactive

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

    import os

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
