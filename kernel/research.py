"""Research Pipeline — исследовательский цикл Эйдоса.

Гипотеза → план → эксперимент → протокол → вывод → интеграция.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from kernel.memory import DATA_ROOT

EXPERIMENTS_ROOT = Path(__file__).resolve().parent.parent / "experiments"


# ─── Банк гипотез ────────────────────────────────────────────────

class HypothesisBank:
    """Управление гипотезами: создание, поиск, обновление статуса."""

    def __init__(self) -> None:
        EXPERIMENTS_ROOT.mkdir(parents=True, exist_ok=True)
        self._index_path = EXPERIMENTS_ROOT / "INDEX.md"

    def create(self, name: str, title: str, hypothesis: str, rationale: str,
               expected_outcome: str, metrics: list[str], tags: list[str] | None = None,
               dependencies: list[str] | None = None) -> Path:
        """Создаёт новый эксперимент с гипотезой."""
        exp_dir = EXPERIMENTS_ROOT / name
        if exp_dir.exists():
            raise FileExistsError(f"Эксперимент {name} уже существует")

        exp_dir.mkdir(parents=True)
        (exp_dir / "src").mkdir()
        (exp_dir / "results").mkdir()

        # HYPOTHESIS.md
        hypothesis_content = (
            f"# {title}\n\n"
            f"**Статус:** запланирован\n"
            f"**Дата:** {time.strftime('%Y-%m-%d %H:%M', time.localtime())}\n"
            f"**Теги:** {', '.join(tags) if tags else '—'}\n"
            f"**Зависимости:** {', '.join(dependencies) if dependencies else 'нет'}\n\n"
            f"## Гипотеза\n\n{hypothesis}\n\n"
            f"## Обоснование\n\n{rationale}\n\n"
            f"## Ожидаемый результат\n\n{expected_outcome}\n\n"
            f"## Метрики успеха\n\n" + "\n".join(f"- {m}" for m in metrics) + "\n\n"
            f"## План\n\n(будет заполнен)\n\n"
            f"## Протокол\n\n(будет заполнен)\n\n"
            f"## Вывод\n\n(будет заполнен)\n"
        )
        (exp_dir / "HYPOTHESIS.md").write_text(hypothesis_content)

        # README.md — заглушка
        (exp_dir / "README.md").write_text(f"# {title}\n\nВывод будет добавлен после эксперимента.\n")

        # INDEX.md
        entry = (
            f"| {time.strftime('%Y-%m-%d %H:%M', time.localtime())} "
            f"| {name} | {title[:40]} | запланирован | {', '.join(tags) if tags else '—'} |\n"
        )

        if not self._index_path.exists():
            self._index_path.write_text(
                "# Индекс экспериментов\n\n"
                "| Дата | Каталог | Название | Статус | Теги |\n"
                "|------|---------|----------|--------|------|\n"
            )

        with self._index_path.open("a") as f:
            f.write(entry)

        return exp_dir

    def list_experiments(self, status: str | None = None) -> list[dict[str, str]]:
        """Список всех экспериментов, опционально фильтр по статусу."""
        if not self._index_path.exists():
            return []
        results = []
        for line in self._index_path.read_text().split("\n"):
            if not line.startswith("| ") or "Дата" in line:
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 5:
                if status is None or parts[3] == status:
                    results.append({
                        "date": parts[0],
                        "dir": parts[1],
                        "title": parts[2],
                        "status": parts[3],
                        "tags": parts[4],
                    })
        return results

    def update_status(self, name: str, status: str, conclusion: str = "") -> None:
        """Обновляет статус эксперимента и записывает вывод."""
        exp_dir = EXPERIMENTS_ROOT / name
        if not exp_dir.exists():
            return

        hyp_path = exp_dir / "HYPOTHESIS.md"
        if hyp_path.exists():
            content = hyp_path.read_text()
            content = content.replace("**Статус:** запланирован", f"**Статус:** {status}")
            content = content.replace("**Статус:** в процессе", f"**Статус:** {status}")
            hyp_path.write_text(content)

        if conclusion:
            readme_path = exp_dir / "README.md"
            readme_path.write_text(f"# {exp_dir.name}\n\n## Вывод\n\n{conclusion}\n")

        # Обновляем INDEX.md
        if self._index_path.exists():
            lines = self._index_path.read_text().split("\n")
            new_lines = []
            for line in lines:
                if f"| {name} |" in line and len(line.split("|")) >= 5:
                    parts = line.split("|")
                    parts[4] = f" {status} "
                    line = "|".join(parts)
                new_lines.append(line)
            self._index_path.write_text("\n".join(new_lines))


# ─── Планировщик эксперимента ────────────────────────────────────

class ExperimentPlanner:
    """Планирование и выполнение шагов эксперимента."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.path = EXPERIMENTS_ROOT / name
        self.protocol_path = self.path / "protocol.log"
        self._start_time: float | None = None

    def plan_step(self, step_num: int, description: str, command: str) -> None:
        """Добавляет шаг в протокол."""
        entry = f"\n## Шаг {step_num}: {description}\n\n"
        entry += f"**Команда:** `{command}`\n\n"
        entry += "**Результат:** (ожидает выполнения)\n"
        with self.protocol_path.open("a") as f:
            f.write(entry)

    def run_step(self, command: str, cwd: str | None = None) -> dict[str, Any]:
        """Запускает шаг эксперимента, замеряет время, возвращает результат."""
        self._start_time = time.time()
        result: dict[str, Any] = {
            "command": command,
            "success": False,
            "stdout": "",
            "stderr": "",
            "elapsed": 0.0,
            "error": None,
        }

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=cwd or str(self.path),
            )
            result["stdout"] = proc.stdout[-2000:] if len(proc.stdout) > 2000 else proc.stdout
            result["stderr"] = proc.stderr[-1000:] if len(proc.stderr) > 1000 else proc.stderr
            result["success"] = proc.returncode == 0
            if proc.returncode != 0:
                result["error"] = f"exit code {proc.returncode}"
        except subprocess.TimeoutExpired:
            result["error"] = "timeout (600s)"
        except Exception as e:
            result["error"] = str(e)

        result["elapsed"] = time.time() - (self._start_time or time.time())

        # Пишем в протокол
        status = "✅" if result["success"] else "❌"
        with self.protocol_path.open("a") as f:
            f.write(f"\n**Результат:** {status} ({result['elapsed']:.1f}s)\n")
            if result["stdout"]:
                f.write(f"```\n{result['stdout'][:500]}\n```\n")
            if result["error"]:
                f.write(f"**Ошибка:** {result['error']}\n")

        return result

    def record_metric(self, name: str, value: float, unit: str = "") -> None:
        """Записывает метрику в протокол."""
        with self.protocol_path.open("a") as f:
            f.write(f"\n**Метрика:** {name} = {value}{unit}\n")


# ─── Фасад исследователя ─────────────────────────────────────────

class Researcher:
    """Единая точка входа для исследовательского цикла."""

    def __init__(self) -> None:
        self.bank = HypothesisBank()

    def propose(self, name: str, title: str, hypothesis: str, rationale: str,
                expected_outcome: str, metrics: list[str],
                tags: list[str] | None = None,
                dependencies: list[str] | None = None) -> ExperimentPlanner:
        """Создаёт гипотезу и возвращает планировщик для эксперимента."""
        self.bank.create(name, title, hypothesis, rationale,
                         expected_outcome, metrics, tags, dependencies)
        return ExperimentPlanner(name)

    def list_open(self) -> list[dict[str, str]]:
        """Все запланированные и в процессе эксперименты."""
        return self.bank.list_experiments(status="запланирован") + \
               self.bank.list_experiments(status="в процессе")

    def list_all(self) -> list[dict[str, str]]:
        return self.bank.list_experiments()

    def conclude(self, name: str, conclusion: str, new_principles: list[str] | None = None) -> None:
        """Завершает эксперимент, фиксирует вывод, интегрирует в семантику."""
        self.bank.update_status(name, "завершён", conclusion)

        # Интеграция в семантическую память
        if new_principles:
            try:
                from kernel.memory import Memory
                memory = Memory()
                for p in new_principles:
                    memory.semantic.store_principle(
                        principle=p,
                        source_ids=[hash(name) % (2**31)],
                        confidence=0.7,
                    )
            except Exception:
                pass

        # Запись в дневник
        try:
            from kernel.journal import Journal
            j = Journal()
            j.write_session(
                title=f"Эксперимент: {name} — завершён",
                content=conclusion[:500],
                tags=["эксперимент"],
                salience=0.8,
            )
        except Exception:
            pass
