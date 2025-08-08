#!/usr/bin/env python3
"""
AI Code Quality Assistant - Автоматический анализатор качества кода
Выполняет комплексную проверку качества кода и создает отчеты
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

console = Console()


class CodeQualityChecker:
    """Класс для проверки качества кода"""

    def __init__(self, project_path: Path = Path.cwd()):
        self.project_path = project_path
        self.src_path = project_path / "src"
        self.results = {}

    def run_command(self, command: List[str]) -> Tuple[int, str, str]:
        """Выполнить команду и вернуть результат"""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=self.project_path
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)

    def check_test_coverage(self) -> Dict:
        """Проверить тестовое покрытие"""
        console.print("[yellow]Проверка тестового покрытия...[/yellow]")
        
        code, stdout, stderr = self.run_command([
            "python", "-m", "pytest",
            "--cov=src",
            "--cov-report=json",
            "--no-header", "-q",
            "-p", "no:sugar"
        ])
        
        coverage_file = self.project_path / "coverage.json"
        if coverage_file.exists():
            with open(coverage_file) as f:
                coverage_data = json.load(f)
                total = coverage_data.get("totals", {}).get("percent_covered", 0)
                files = coverage_data.get("files", {})
                
                return {
                    "total_coverage": round(total, 2),
                    "files": {
                        Path(f).name: round(data.get("summary", {}).get("percent_covered", 0), 2)
                        for f, data in files.items()
                    },
                    "status": "✅" if total >= 80 else "⚠️" if total >= 60 else "🔴"
                }
        
        return {"total_coverage": 0, "files": {}, "status": "🔴"}

    def check_code_style(self) -> Dict:
        """Проверить стиль кода с помощью flake8"""
        console.print("[yellow]Проверка стиля кода (flake8)...[/yellow]")
        
        code, stdout, stderr = self.run_command([
            "python", "-m", "flake8",
            "src/",
            "--count",
            "--statistics",
            "--output-file=flake8_report.txt"
        ])
        
        # Парсим вывод flake8
        issues = []
        stats = {}
        
        if stdout:
            lines = stdout.strip().split('\n')
            for line in lines:
                if line and not line.isdigit():
                    parts = line.split()
                    if len(parts) >= 2:
                        count = int(parts[0])
                        code = parts[1]
                        stats[code] = count
        
        total_issues = sum(stats.values()) if stats else 0
        
        return {
            "total_issues": total_issues,
            "statistics": stats,
            "status": "✅" if total_issues == 0 else "⚠️" if total_issues <= 50 else "🔴"
        }

    def check_complexity(self) -> Dict:
        """Проверить цикломатическую сложность"""
        console.print("[yellow]Проверка сложности кода...[/yellow]")
        
        # Проверяем, установлен ли radon
        code, stdout, stderr = self.run_command(["python", "-m", "pip", "show", "radon"])
        if code != 0:
            console.print("[yellow]Пакет radon не установлен, пропускаем проверку сложности[/yellow]")
            return {"complex_functions": [], "status": "❓", "note": "radon не установлен"}
        
        try:
            code, stdout, stderr = self.run_command([
                "python", "-m", "radon", "cc",
                "src/", "-s", "-j"
            ])
            
            if stdout:
                complexity_data = json.loads(stdout)
                complex_functions = []
                
                for file, functions in complexity_data.items():
                    for func in functions:
                        if func["complexity"] > 10:
                            complex_functions.append({
                                "file": Path(file).name,
                                "function": func["name"],
                                "complexity": func["complexity"]
                            })
                
                return {
                    "complex_functions": complex_functions,
                    "status": "✅" if not complex_functions else "⚠️"
                }
        except Exception as e:
            console.print(f"[red]Ошибка при проверке сложности: {e}[/red]")
            return {"complex_functions": [], "status": "❓"}

    def check_dependencies(self) -> Dict:
        """Проверить устаревшие зависимости"""
        console.print("[yellow]Проверка зависимостей...[/yellow]")
        
        code, stdout, stderr = self.run_command([
            "pip", "list", "--outdated", "--format=json"
        ])
        
        outdated = []
        critical_packages = ["cryptography", "django", "pillow", "pyyaml", "requests", "sqlalchemy"]
        
        if stdout:
            try:
                packages = json.loads(stdout)
                for pkg in packages:
                    if pkg["name"].lower() in critical_packages:
                        outdated.append({
                            "name": pkg["name"],
                            "current": pkg["version"],
                            "latest": pkg["latest_version"]
                        })
            except:
                pass
        
        return {
            "outdated_critical": outdated,
            "status": "✅" if not outdated else "🔴"
        }

    def generate_report(self) -> str:
        """Генерировать отчет в формате Markdown"""
        report = []
        report.append("# 📊 Отчет о качестве кода")
        report.append(f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("")
        
        # Тестовое покрытие
        coverage = self.results.get("coverage", {})
        if coverage:
            report.append(f"## Тестовое покрытие {coverage.get('status', '❓')}")
            report.append(f"**Общее покрытие:** {coverage.get('total_coverage', 0)}%")
            report.append("")
        
        # Стиль кода
        style = self.results.get("style", {})
        if style:
            report.append(f"## Стиль кода {style.get('status', '❓')}")
            report.append(f"**Всего проблем:** {style.get('total_issues', 0)}")
            if style.get("statistics"):
                report.append("### Детализация:")
                for code, count in sorted(style["statistics"].items()):
                    report.append(f"- {code}: {count}")
            report.append("")
        
        # Сложность
        complexity = self.results.get("complexity", {})
        if complexity:
            report.append(f"## Сложность кода {complexity.get('status', '❓')}")
            if complexity.get("complex_functions"):
                report.append("### Функции с высокой сложностью:")
                for func in complexity["complex_functions"]:
                    report.append(f"- {func['file']}/{func['function']}: {func['complexity']}")
            else:
                report.append("Все функции имеют приемлемую сложность ✅")
            report.append("")
        
        # Зависимости
        deps = self.results.get("dependencies", {})
        report.append(f"## Зависимости {deps.get('status', '❓')}")
        if deps.get("outdated_critical"):
            report.append("### Критические устаревшие пакеты:")
            for pkg in deps["outdated_critical"]:
                report.append(f"- **{pkg['name']}**: {pkg['current']} → {pkg['latest']}")
        else:
            report.append("Все критические зависимости актуальны ✅")
        
        return "\n".join(report)

    def print_summary(self):
        """Вывести сводку в консоль"""
        table = Table(title="Сводка качества кода")
        table.add_column("Метрика", style="cyan")
        table.add_column("Статус", style="white")
        table.add_column("Значение", style="white")
        
        coverage = self.results.get("coverage", {})
        table.add_row(
            "Тестовое покрытие",
            coverage.get("status", "❓"),
            f"{coverage.get('total_coverage', 0)}%"
        )
        
        style = self.results.get("style", {})
        table.add_row(
            "Стиль кода",
            style.get("status", "❓"),
            f"{style.get('total_issues', 0)} проблем"
        )
        
        complexity = self.results.get("complexity") or {}
        complex_count = len(complexity.get("complex_functions", []))
        table.add_row(
            "Сложность",
            complexity.get("status", "❓"),
            f"{complex_count} сложных функций" if not complexity.get("note") else complexity.get("note")
        )
        
        deps = self.results.get("dependencies", {})
        outdated_count = len(deps.get("outdated_critical", []))
        table.add_row(
            "Зависимости",
            deps.get("status", "❓"),
            f"{outdated_count} устаревших"
        )
        
        console.print(table)

    def run_checks(self):
        """Запустить все проверки"""
        console.print(Panel.fit("🚀 Запуск проверки качества кода", style="bold blue"))
        
        self.results["coverage"] = self.check_test_coverage()
        self.results["style"] = self.check_code_style()
        self.results["complexity"] = self.check_complexity()
        self.results["dependencies"] = self.check_dependencies()
        
        return self.results


@click.command()
@click.option("--format", "-f", type=click.Choice(["console", "markdown", "json"]), 
              default="console", help="Формат вывода отчета")
@click.option("--output", "-o", type=click.Path(), help="Файл для сохранения отчета")
@click.option("--fix", is_flag=True, help="Автоматически исправить проблемы форматирования")
def main(format, output, fix):
    """AI Code Quality Assistant - проверка качества кода"""
    
    checker = CodeQualityChecker()
    
    if fix:
        console.print("[green]Автоматическое исправление форматирования...[/green]")
        checker.run_command(["python", "-m", "black", "src/", "--line-length", "120"])
        checker.run_command(["python", "-m", "isort", "src/", "--line-length", "120"])
        console.print("[green]✅ Форматирование завершено[/green]")
    
    # Запускаем проверки
    results = checker.run_checks()
    
    # Выводим результаты
    if format == "console":
        checker.print_summary()
    elif format == "markdown":
        report = checker.generate_report()
        if output:
            Path(output).write_text(report)
            console.print(f"[green]Отчет сохранен в {output}[/green]")
        else:
            print(report)
    elif format == "json":
        json_report = json.dumps(results, indent=2)
        if output:
            Path(output).write_text(json_report)
            console.print(f"[green]JSON отчет сохранен в {output}[/green]")
        else:
            print(json_report)
    
    # Определяем код возврата
    if results.get("coverage", {}).get("total_coverage", 0) < 60:
        sys.exit(1)
    if results.get("style", {}).get("total_issues", 0) > 100:
        sys.exit(1)
    if results.get("dependencies", {}).get("outdated_critical"):
        console.print("[yellow]⚠️ Обнаружены устаревшие критические зависимости[/yellow]")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
