#!/usr/bin/env python3
import os
import sys
import json
import time
import typing as t

import click
from dotenv import load_dotenv

# Optional: import lazily to give nicer errors if lib missing
try:
    import google.generativeai as genai
except Exception as e:  # pragma: no cover
    genai = None  # type: ignore


def _load_env() -> None:
    load_dotenv(override=False)


def _get_api_keys() -> list[str]:
    keys_csv = os.getenv("GOOGLE_API_KEYS", "").strip()
    if keys_csv:
        return [k.strip() for k in keys_csv.split(",") if k.strip()]
    single = os.getenv("GOOGLE_API_KEY", "").strip()
    return [single] if single else []


def _configure_genai(key_index: int | None) -> tuple[str | None, str]:
    api_keys = _get_api_keys()
    if not api_keys:
        return None, "GOOGLE_API_KEYS/GOOGLE_API_KEY not configured"

    idx = 0 if key_index is None else key_index
    if idx < 0 or idx >= len(api_keys):
        return None, f"key_index out of range (0..{len(api_keys)-1})"

    key = api_keys[idx]
    if genai is None:
        return None, "google-generativeai is not installed. Add it to requirements and pip install."

    genai.configure(api_key=key)
    return key, "ok"


def _default_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


@click.group()
def cli() -> None:
    """Gemini CLI orchestration tool."""
    _load_env()


@cli.command()
@click.option("-q", "prompt", required=True, help="Prompt text")
@click.option("--model", default=None, help="Model name (overrides GEMINI_MODEL)")
@click.option("--key-index", type=int, default=None, help="Index of GOOGLE_API_KEYS to use")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output")
def prompt(prompt: str, model: str | None, key_index: int | None, as_json: bool) -> None:
    """Send single prompt to Gemini and print completion."""
    key, status = _configure_genai(key_index)
    if key is None:
        click.echo(status, err=True)
        sys.exit(2)

    model_name = model or _default_model()
    started = time.time()
    try:
        mdl = genai.GenerativeModel(model_name)
        resp = mdl.generate_content(prompt)
        text = getattr(resp, "text", "")
        elapsed_ms = int((time.time() - started) * 1000)
        if as_json:
            out = {"ok": True, "model": model_name, "key_index": key_index or 0, "elapsed_ms": elapsed_ms, "text": text}
            click.echo(json.dumps(out, ensure_ascii=False))
        else:
            click.echo(text)
            click.echo(f"\n[ok model={model_name} key_index={key_index or 0} elapsed_ms={elapsed_ms}ms]", err=True)
    except Exception as e:
        if as_json:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
        else:
            click.echo(f"error: {e}", err=True)
        sys.exit(1)


@cli.command(name="summarize-file")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--model", default=None)
@click.option("--key-index", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def summarize_file(path: str, model: str | None, key_index: int | None, as_json: bool) -> None:
    """Summarize a local text/markdown/html file."""
    key, status = _configure_genai(key_index)
    if key is None:
        click.echo(status, err=True)
        sys.exit(2)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    model_name = model or _default_model()
    prompt = (
        "Суммируй файл кратко и по пунктам (bullets). Если это код — дай выжимку ключевых частей.\n\n" + content
    )
    started = time.time()
    try:
        mdl = genai.GenerativeModel(model_name)
        resp = mdl.generate_content(prompt)
        text = getattr(resp, "text", "")
        elapsed_ms = int((time.time() - started) * 1000)
        if as_json:
            out = {"ok": True, "model": model_name, "key_index": key_index or 0, "elapsed_ms": elapsed_ms, "text": text}
            click.echo(json.dumps(out, ensure_ascii=False))
        else:
            click.echo(text)
            click.echo(f"\n[ok model={model_name} key_index={key_index or 0} elapsed_ms={elapsed_ms}ms]", err=True)
    except Exception as e:
        if as_json:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
        else:
            click.echo(f"error: {e}", err=True)
        sys.exit(1)


@cli.command(name="models:list")
@click.option("--json", "as_json", is_flag=True)
@click.option("--key-index", type=int, default=None)
def models_list(as_json: bool, key_index: int | None) -> None:
    """List available models for current key."""
    key, status = _configure_genai(key_index)
    if key is None:
        click.echo(status, err=True)
        sys.exit(2)
    try:
        models = list(genai.list_models())
        names = [m.name for m in models]
        if as_json:
            click.echo(json.dumps({"ok": True, "models": names}, ensure_ascii=False))
        else:
            for n in names:
                click.echo(n)
    except Exception as e:
        if as_json:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
        else:
            click.echo(f"error: {e}", err=True)
        sys.exit(1)


@cli.command(name="keys:check")
@click.option("--json", "as_json", is_flag=True)
def keys_check(as_json: bool) -> None:
    """Probe each configured key with a tiny request."""
    keys = _get_api_keys()
    if not keys:
        click.echo("no GOOGLE_API_KEYS/GOOGLE_API_KEY configured", err=True)
        sys.exit(2)

    results: list[dict[str, t.Any]] = []
    for idx in range(len(keys)):
        key, status = _configure_genai(idx)
        if key is None:
            results.append({"index": idx, "ok": False, "error": status})
            continue
        started = time.time()
        try:
            mdl = genai.GenerativeModel(_default_model())
            resp = mdl.generate_content("ok?")
            text = getattr(resp, "text", "")
            elapsed_ms = int((time.time() - started) * 1000)
            results.append({"index": idx, "ok": True, "elapsed_ms": elapsed_ms, "sample": text[:60]})
        except Exception as e:
            results.append({"index": idx, "ok": False, "error": str(e)})

    if as_json:
        click.echo(json.dumps({"results": results}, ensure_ascii=False))
    else:
        for r in results:
            if r.get("ok"):
                click.echo(f"[{r['index']}] OK {r.get('elapsed_ms')}ms")
            else:
                click.echo(f"[{r['index']}] FAIL {r.get('error')}")


@cli.command(name="keys:rotate")
@click.option("--current-index", type=int, required=True)
@click.option("--json", "as_json", is_flag=True)
def keys_rotate(current_index: int, as_json: bool) -> None:
    """Return next key index in cycle based on current index."""
    keys = _get_api_keys()
    if not keys:
        click.echo("no GOOGLE_API_KEYS/GOOGLE_API_KEY configured", err=True)
        sys.exit(2)

    nxt = (current_index + 1) % len(keys)
    if as_json:
        click.echo(json.dumps({"next_index": nxt}))
    else:
        click.echo(str(nxt))


if __name__ == "__main__":
    cli()
