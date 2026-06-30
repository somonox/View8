#!/usr/bin/env python3
"""
Recover source-like JavaScript from View8 SNIR constant pools.

This is intentionally conservative: V8 cachedData does not contain the original
source text, so the script reconstructs what can be proven from constants and
known bytecode/export shapes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def load_snir(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def largest_constant_pool_function(snir: dict[str, Any]) -> dict[str, Any]:
    functions = snir.get("functions", [])
    if not functions:
        raise ValueError("SNIR contains no functions")
    return max(functions, key=lambda f: len(f.get("constant_pool", [])))


def function_by_name(snir: dict[str, Any], name: str) -> dict[str, Any] | None:
    for fn in snir.get("functions", []):
        if fn.get("name") == name:
            return fn
    return None


def fix_v8_literal(value: str) -> str:
    """Normalize V8 printer spellings such as <true and false> to JS syntax."""
    value = value.replace("<true", "true")
    value = value.replace("<false", "false")
    value = value.replace("<null", "null")
    return re.sub(r"\b(true|false|null)>", r"\1", value)


def object_literals(constant_pool: list[Any]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for idx, value in enumerate(constant_pool):
        if isinstance(value, str) and value.strip().startswith("{"):
            out.append((idx, fix_v8_literal(value)))
    return out


def setting_entry_literals(constant_pool: list[Any]) -> list[tuple[int, str, str]]:
    entries: list[tuple[int, str, str]] = []
    for idx, value in object_literals(constant_pool):
        if idx == 25:
            continue
        match = re.search(r'"id":\s*"([^"]+)"', value)
        if match:
            entries.append((idx, match.group(1), value))
    return entries


def infer_kind(snir: dict[str, Any]) -> str:
    main = largest_constant_pool_function(snir)
    pool = main.get("constant_pool", [])
    exports = {v.strip('"') for v in pool if isinstance(v, str)}
    if {"getUserscriptSettings", "hasUserscriptSettings", "addUserscriptSettings"} <= exports:
        return "settings"
    return "generic"


def safe_pool_get(pool: list[Any], idx: int, description: str) -> str:
    try:
        value = pool[idx]
    except IndexError as exc:
        raise ValueError(f"missing constant_pool[{idx}] for {description}") from exc
    if not isinstance(value, str):
        raise ValueError(f"constant_pool[{idx}] for {description} is not a string")
    return fix_v8_literal(value)


def render_settings_module(snir: dict[str, Any], source_label: str) -> str:
    main = largest_constant_pool_function(snir)
    pool = main.get("constant_pool", [])
    entries = setting_entry_literals(pool)

    header = f'''/*
 * Recovered from {source_label} bytenode cached bytecode.
 *
 * This is a source-level reconstruction, not the original authoring file.
 * V8 cachedData preserves object literals, strings, and bytecode behavior, but
 * not comments, formatting, local variable names, or exact statement layout.
 */

"use strict";

function optionalRequire(name) {{
  try {{
    return require(name);
  }} catch (_) {{
    return null;
  }}
}}

const electron = optionalRequire("electron") || {{}};
const ipcRenderer = electron.ipcRenderer || null;
const path = optionalRequire("path");
const log = optionalRequire("electron-log") || console;
const Store = optionalRequire("electron-store");
const config = Store ? new Store() : {{ get: (_key, fallback) => fallback }};

let lang = {{}};
try {{
  const locale = config.get("lang", "en_US");
  const base = path && __dirname ? path.join(__dirname, "../../lang/", locale) : null;
  lang = base ? require(base) : {{}};
}} catch (_) {{
  lang = {{}};
}}

if (log && typeof log.info === "function") {{
  log.info("Script Loaded: js/util/settings.js");
}}

'''

    parts = [header]
    parts.append("const clientBindSettings = " + safe_pool_get(pool, 13, "client bind settings") + ";\n\n")
    parts.append("const matchmakerSettings = " + safe_pool_get(pool, 14, "matchmaker settings") + ";\n\n")
    parts.append(
        "const InboxNotificationUtilSettings = "
        + safe_pool_get(pool, 15, "inbox notification settings")
        + ";\n\n"
    )
    parts.append("const rankCommandObj = " + safe_pool_get(pool, 16, "rank command object") + ";\n\n")
    parts.append("const userscriptSettings = " + safe_pool_get(pool, 18, "userscript settings") + ";\n\n")
    parts.append("const settings = " + safe_pool_get(pool, 25, "settings skeleton") + ";\n\n")

    parts.append("const recoveredSettingEntries = [\n")
    for idx, ident, literal in entries:
        parts.append(f"  // constant_pool[{idx}] id={ident}\n")
        parts.append(f"  {literal},\n")
    parts.append("];\n\n")

    parts.append(r'''for (const entry of recoveredSettingEntries) {
  if (entry && entry.id) {
    settings[entry.id] = entry;
  }
}

settings.clientBindSettings = settings.clientBindSettings || clientBindSettings;
settings.matchmakerSettings = settings.matchmakerSettings || matchmakerSettings;
settings.InboxNotificationUtilSettings = settings.InboxNotificationUtilSettings || InboxNotificationUtilSettings;
settings.twitchChannelPointsUtil = settings.twitchChannelPointsUtil || rankCommandObj;
settings.BindOptions = settings.BindOptions || clientBindSettings;

function getChannelRewardSettingsObj() {
  const result = {};
  for (const key of Object.keys(rankCommandObj)) {
    const reward = rankCommandObj[key];
    const assignKey = `${key.split("_toggle")[0]}_assign`;
    result[assignKey] = {
      title: `${reward.title} - Reward`,
      desc: `${reward.desc} | ID: unset`,
      type: "button_assign",
      refresh: reward.refresh,
      val: "unset",
      onclick: "window.gt.captureEventID(this)",
    };
  }
  return result;
}

settings.twitchChannelPointsOptions = settings.twitchChannelPointsOptions || getChannelRewardSettingsObj();

function getUserscriptSettings() {
  return userscriptSettings;
}

function hasUserscriptSettings(id) {
  return Object.prototype.hasOwnProperty.call(userscriptSettings, id);
}

function addUserscriptSettings(settingsObject, scriptName) {
  if (!scriptName) {
    return;
  }

  if (!settingsObject) {
    log.info(`[USERSCRIPT] Error: Script '${scriptName}' attempted to call SettingsUtil will a null or empty argument for the settings object...`);
    return;
  }

  let parsedSettings;
  try {
    parsedSettings = typeof settingsObject === "string" ? JSON.parse(settingsObject) : settingsObject;
  } catch (_) {
    log.info(`[USERSCRIPT] Error: Script '${scriptName}' passed an object to SettingsUtil that could not be parsed...`);
    return;
  }

  const safeScriptName = String(scriptName).replace(/\s+/g, "");
  const optionsId = `${safeScriptName}_OPTIONS`;

  userscriptSettings[optionsId] = {
    id: optionsId,
    title: "data",
    type: "data",
    cat: "data",
    info: "data",
    val: config.get(optionsId, parsedSettings),
    default: parsedSettings,
  };

  settings[safeScriptName] = {
    id: safeScriptName,
    title: `${scriptName} Script Options`,
    cat: "Utilities - Userscript Options",
    type: "button",
    onclick: `window.gt.makeOptionsPopup("${optionsId}");`,
    val: config.get(safeScriptName, true),
    default: true,
  };

  Object.assign(module.exports.settings, settings);

  if (ipcRenderer && typeof ipcRenderer.invoke === "function") {
    ipcRenderer.invoke("restoreSettings", userscriptSettings);
  }
}

module.exports = {
  settings,
  clientBindSettings,
  matchmakerSettings,
  InboxNotificationUtilSettings,
  rankCommandObj,
  userscriptSettings,
  getChannelRewardSettingsObj,
  getUserscriptSettings,
  hasUserscriptSettings,
  addUserscriptSettings,
  lang,
};
''')
    return "".join(parts)


def render_generic_module(snir: dict[str, Any], source_label: str) -> str:
    constants_by_function: dict[str, list[Any]] = {}
    object_constants: dict[str, list[dict[str, Any]]] = {}
    for fn in snir.get("functions", []):
        name = fn.get("name", "anonymous")
        pool = fn.get("constant_pool", [])
        constants_by_function[name] = pool
        object_constants[name] = [
            {"index": idx, "literal": literal}
            for idx, literal in object_literals(pool)
        ]

    return '''/*
 * Generic constant-pool recovery from %s.
 * This file exposes extracted constants; it is not a full decompilation.
 */

"use strict";

const constantsByFunction = %s;

const objectConstants = %s;

module.exports = {
  constantsByFunction,
  objectConstants,
};
''' % (
        source_label,
        json.dumps(constants_by_function, ensure_ascii=False, indent=2),
        json.dumps(object_constants, ensure_ascii=False, indent=2),
    )


def write_output(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def run_node_check(path: Path) -> None:
    subprocess.run(["node", "--check", str(path)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snir", type=Path, help="View8 SNIR JSON input")
    parser.add_argument("--out", type=Path, required=True, help="Recovered JS output")
    parser.add_argument(
        "--kind",
        choices=["auto", "generic", "settings"],
        default="auto",
        help="Recovery template to apply",
    )
    parser.add_argument("--source-label", default=None, help="Human-readable source path for file header")
    parser.add_argument("--check", action="store_true", help="Run node --check on the generated file")
    args = parser.parse_args()

    snir = load_snir(args.snir)
    kind = infer_kind(snir) if args.kind == "auto" else args.kind
    source_label = args.source_label or os.path.basename(args.snir)

    if kind == "settings":
        recovered = render_settings_module(snir, source_label)
    else:
        recovered = render_generic_module(snir, source_label)

    write_output(args.out, recovered)
    if args.check:
        run_node_check(args.out)

    main_fn = largest_constant_pool_function(snir)
    print(
        json.dumps(
            {
                "input": str(args.snir),
                "output": str(args.out),
                "kind": kind,
                "main_function": main_fn.get("name"),
                "constant_pool_size": len(main_fn.get("constant_pool", [])),
                "object_constants": len(object_literals(main_fn.get("constant_pool", []))),
                "setting_entries": len(setting_entry_literals(main_fn.get("constant_pool", []))),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
