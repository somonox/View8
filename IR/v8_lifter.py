import ast
import re


SCHEMA_VERSION = "view8-snir-v1"


def split_instruction(instruction):
    operator, *arg_text = instruction.split(" ", 1)
    operator = operator.split(".")[0]
    args = arg_text[0].split(", ") if arg_text else []
    return operator, args


def parse_int_token(token):
    token = token.strip()
    if token.startswith("#"):
        return int(token[1:])
    if token.startswith("@"):
        return int(token[1:])
    return int(token)


def parse_jump_target(args):
    if not args:
        return None
    match = re.search(r"@(-?\d+)", args[-1])
    if match:
        return int(match.group(1))
    match = re.search(r"(-?\d+)\)?$", args[-1])
    if match:
        return int(match.group(1))
    return None


def parse_register_range(token):
    if "-" not in token:
        return None
    start, end = token.split("-", 1)
    if not re.fullmatch(r"[ra]\d+", start) or not re.fullmatch(r"[ra]\d+", end):
        return None
    prefix = start[0]
    if end[0] != prefix:
        return None
    return [f"{prefix}{idx}" for idx in range(int(start[1:]), int(end[1:]) + 1)]


def parse_operand(token):
    token = token.strip()
    reg_range = parse_register_range(token)
    if reg_range is not None:
        return {"kind": "register_range", "text": token, "registers": reg_range}
    if token == "<this>":
        return {"kind": "this", "text": token}
    if re.fullmatch(r"r\d+", token):
        return {"kind": "register", "text": token, "name": token}
    if re.fullmatch(r"a\d+", token):
        return {"kind": "argument", "text": token, "name": token}
    if re.fullmatch(r"#-?\d+", token):
        return {"kind": "immediate", "text": token, "value": parse_int_token(token)}
    if re.fullmatch(r"\[\d+\]", token):
        return {"kind": "constant_pool_index", "text": token, "index": int(token[1:-1])}
    if re.fullmatch(r"@\d+", token):
        return {"kind": "bytecode_offset", "text": token, "offset": parse_int_token(token)}
    if token.startswith("<") and token.endswith(">"):
        return {"kind": "runtime_symbol", "text": token, "name": token[1:-1]}
    return {"kind": "raw", "text": token}


def registers_from_operand(operand):
    if operand["kind"] == "register":
        return [operand["name"]]
    if operand["kind"] == "register_range":
        return operand["registers"]
    return []


def const_refs_from_operand(operand):
    if operand["kind"] == "constant_pool_index":
        return [operand["index"]]
    return []


def add_reads_from_operands(reads, operands):
    for operand in operands:
        reads["registers"].extend(registers_from_operand(operand))
        reads["constants"].extend(const_refs_from_operand(operand))


def unique(values):
    return list(dict.fromkeys(values))


def normalize_access(access):
    return {
        "accumulator": access["accumulator"],
        "registers": unique(access["registers"]),
        "arguments": unique(access["arguments"]),
        "constants": unique(access["constants"]),
        "contexts": unique(access["contexts"]),
    }


def empty_access():
    return {
        "accumulator": False,
        "registers": [],
        "arguments": [],
        "constants": [],
        "contexts": [],
    }


def classify_control_flow(opcode, args):
    target = parse_jump_target(args)
    if opcode in {"Return", "Throw", "ReThrow"}:
        return {"kind": "terminal"}
    if opcode.startswith("JumpIf"):
        return {"kind": "conditional_jump", "target": target, "target_condition": jump_condition(opcode)}
    if opcode.startswith("JumpLoop"):
        return {"kind": "loop_backedge", "target": target}
    if opcode.startswith("Jump"):
        return {"kind": "unconditional_jump", "target": target}
    if opcode == "SwitchOnSmiNoFeedback":
        return {"kind": "switch", "targets": parse_switch_targets(args)}
    if opcode == "SwitchOnGeneratorState":
        return {"kind": "generator_switch"}
    return {"kind": "fallthrough"}


def jump_condition(opcode):
    if opcode.endswith("Constant"):
        opcode = opcode[:-len("Constant")]
    conditions = {
        "JumpIfTrue": "acc",
        "JumpIfFalse": "!acc",
        "JumpIfNull": "acc == null",
        "JumpIfNotNull": "acc != null",
        "JumpIfUndefined": "acc == undefined",
        "JumpIfNotUndefined": "acc != undefined",
        "JumpIfUndefinedOrNull": "acc == undefined || acc == null",
        "JumpIfToBooleanTrue": "to_boolean(acc)",
        "JumpIfToBooleanFalse": "!to_boolean(acc)",
        "JumpIfJSReceiver": "is_js_receiver(acc)",
    }
    return conditions.get(opcode, f"{opcode}(acc)")


def invert_condition(condition):
    inversions = {
        "acc": "!acc",
        "!acc": "acc",
        "acc == null": "acc != null",
        "acc != null": "acc == null",
        "acc == undefined": "acc != undefined",
        "acc != undefined": "acc == undefined",
        "acc == undefined || acc == null": "acc != undefined && acc != null",
        "to_boolean(acc)": "!to_boolean(acc)",
        "!to_boolean(acc)": "to_boolean(acc)",
        "is_js_receiver(acc)": "!is_js_receiver(acc)",
    }
    return inversions.get(condition, f"!({condition})")


def parse_switch_targets(args):
    line = ",".join(args)
    start = line.find("{")
    if start == -1:
        return []
    try:
        table = ast.literal_eval(line[start:].replace("@", ""))
    except Exception:
        return []
    return [{"case": key, "target": value} for key, value in sorted(table.items(), key=lambda item: item[1])]


def opcode_effect(opcode):
    if opcode.startswith("Call") or opcode == "InvokeIntrinsic":
        return "call"
    if opcode.startswith("Construct"):
        return "construct"
    if opcode.startswith("Create"):
        return "allocate"
    if opcode.startswith(("Sta", "Set", "Define")):
        return "store"
    if opcode.startswith(("Lda", "Get")) or opcode.startswith("Mov"):
        return "load"
    if opcode.startswith("Test"):
        return "compare"
    if opcode.startswith(("Add", "Sub", "Mul", "Div", "Mod", "Exp", "Bitwise", "Shift")):
        return "binary_op"
    if opcode in {"Inc", "Dec", "Negate", "BitwiseNot", "LogicalNot"} or opcode.startswith("To"):
        return "unary_op"
    if opcode.startswith("Jump") or opcode in {"Return", "Throw", "ReThrow", "SwitchOnSmiNoFeedback", "SwitchOnGeneratorState"}:
        return "control"
    if "Context" in opcode:
        return "context"
    if opcode.startswith("ForIn"):
        return "iterator"
    if opcode in {"SuspendGenerator", "ResumeGenerator"}:
        return "generator"
    return "unknown"


def lift_instruction(line):
    opcode, raw_args = split_instruction(line.v8_instruction)
    operands = [parse_operand(arg) for arg in raw_args]
    reads = empty_access()
    writes = empty_access()
    effects = []

    effect = opcode_effect(opcode)
    if effect != "unknown":
        effects.append(effect)

    if opcode.startswith(("Lda", "Get", "Create")) or opcode in {"Mov", "ForInEnumerate"}:
        writes["accumulator"] = True
        add_reads_from_operands(reads, operands)
    elif opcode.startswith("Star") or opcode.startswith("Sta") or opcode.startswith(("Set", "Define")):
        reads["accumulator"] = True
        add_reads_from_operands(reads, operands)
        if opcode == "Star":
            writes["registers"].append(raw_args[0])
        elif opcode.startswith("Star") and opcode[4:].isdigit():
            writes["registers"].append(f"r{opcode[4:]}")
        elif "Context" in opcode:
            writes["contexts"].append("context_slot")
    elif opcode.startswith(("Call", "Construct")) or opcode in {"InvokeIntrinsic", "CallRuntime", "CallJSRuntime"}:
        writes["accumulator"] = True
        add_reads_from_operands(reads, operands)
        if operands:
            reads["accumulator"] = True
    elif opcode.startswith("Test") or opcode.startswith(("Add", "Sub", "Mul", "Div", "Mod", "Exp", "Bitwise", "Shift")):
        reads["accumulator"] = True
        writes["accumulator"] = True
        add_reads_from_operands(reads, operands)
    elif opcode in {"Inc", "Dec", "Negate", "BitwiseNot", "LogicalNot"} or opcode.startswith("To"):
        reads["accumulator"] = True
        writes["accumulator"] = True
    elif opcode.startswith("JumpIf") or opcode in {"Return", "Throw", "ReThrow", "SwitchOnSmiNoFeedback"}:
        reads["accumulator"] = True
        add_reads_from_operands(reads, operands)
    else:
        add_reads_from_operands(reads, operands)

    for operand in operands:
        if operand["kind"] == "argument":
            reads["arguments"].append(operand["name"])

    control_flow = classify_control_flow(opcode, raw_args)
    return {
        "offset": line.line_num,
        "opcode": opcode,
        "raw": line.v8_instruction,
        "operands": operands,
        "reads": normalize_access(reads),
        "writes": normalize_access(writes),
        "effects": effects,
        "control_flow": control_flow,
    }


def next_offset(offsets, offset):
    idx = offsets.index(offset)
    if idx + 1 >= len(offsets):
        return None
    return offsets[idx + 1]


def build_basic_blocks(instructions, exception_table):
    offsets = [instruction["offset"] for instruction in instructions]
    instruction_by_offset = {instruction["offset"]: instruction for instruction in instructions}
    leaders = {offsets[0]} if offsets else set()

    for instruction in instructions:
        flow = instruction["control_flow"]
        kind = flow["kind"]
        if flow.get("target") in instruction_by_offset:
            leaders.add(flow["target"])
        for target in [item["target"] for item in flow.get("targets", [])]:
            if target in instruction_by_offset:
                leaders.add(target)
        if kind != "fallthrough":
            fallthrough = next_offset(offsets, instruction["offset"])
            if fallthrough is not None:
                leaders.add(fallthrough)

    for catch_start, try_range in exception_table.items():
        if catch_start in instruction_by_offset:
            leaders.add(catch_start)
        if try_range and try_range[0] in instruction_by_offset:
            leaders.add(try_range[0])

    sorted_leaders = sorted(leaders)
    offset_to_block = {}
    blocks = []
    for idx, start in enumerate(sorted_leaders):
        end_limit = sorted_leaders[idx + 1] if idx + 1 < len(sorted_leaders) else None
        block_instructions = [
            instruction for instruction in instructions
            if instruction["offset"] >= start and (end_limit is None or instruction["offset"] < end_limit)
        ]
        if not block_instructions:
            continue
        block_id = f"bb{len(blocks)}"
        for instruction in block_instructions:
            offset_to_block[instruction["offset"]] = block_id
        blocks.append({
            "id": block_id,
            "start": block_instructions[0]["offset"],
            "end": block_instructions[-1]["offset"],
            "instructions": block_instructions,
            "successors": [],
            "predecessors": [],
            "exception_handlers": [],
        })

    for block in blocks:
        block["successors"] = block_successors(block, offsets, offset_to_block)
        block["exception_handlers"] = block_exception_handlers(block, exception_table, offset_to_block)

    predecessors = {block["id"]: [] for block in blocks}
    for block in blocks:
        for successor in block["successors"]:
            predecessors.setdefault(successor["block"], []).append({"block": block["id"], "edge": successor["edge"]})
        for handler in block["exception_handlers"]:
            predecessors.setdefault(handler["block"], []).append({"block": block["id"], "edge": "exception"})
    for block in blocks:
        block["predecessors"] = predecessors.get(block["id"], [])

    return blocks


def block_successors(block, offsets, offset_to_block):
    last = block["instructions"][-1]
    flow = last["control_flow"]
    successors = []

    def add(edge, target):
        block_id = offset_to_block.get(target)
        if block_id is not None:
            successors.append({"edge": edge, "target": target, "block": block_id})

    kind = flow["kind"]
    if kind == "conditional_jump":
        condition = flow.get("target_condition", "condition")
        add(condition, flow.get("target"))
        fallthrough = next_offset(offsets, last["offset"])
        add(invert_condition(condition), fallthrough)
    elif kind == "loop_backedge":
        add("backedge", flow.get("target"))
    elif kind == "unconditional_jump":
        add("jump", flow.get("target"))
    elif kind == "switch":
        for case in flow.get("targets", []):
            add(f"case:{case['case']}", case["target"])
    elif kind == "fallthrough":
        fallthrough = next_offset(offsets, last["offset"])
        add("fallthrough", fallthrough)

    return successors


def block_exception_handlers(block, exception_table, offset_to_block):
    handlers = []
    for catch_start, try_range in exception_table.items():
        if not try_range:
            continue
        try_start, try_end = try_range
        if block["start"] < try_end and block["end"] >= try_start:
            block_id = offset_to_block.get(catch_start)
            if block_id is not None:
                handlers.append({"catch_offset": catch_start, "block": block_id, "try_range": try_range})
    return handlers


def evidence(line, source, confidence=1.0, note=None):
    item = {
        "source": source,
        "offset": line.line_num,
        "opcode": split_instruction(line.v8_instruction)[0],
        "raw": line.v8_instruction,
        "confidence": confidence,
    }
    if note:
        item["note"] = note
    return item


def make_fact(fact_id, relation, subject, value, evidence_items, confidence=1.0, alternatives=None):
    fact = {
        "id": fact_id,
        "relation": relation,
        "subject": subject,
        "value": value,
        "confidence": confidence,
        "evidence": evidence_items,
    }
    if alternatives:
        fact["alternatives"] = alternatives
    return fact


def add_fact(facts, relation, subject, value, evidence_items, confidence=1.0, alternatives=None):
    fact_id = f"fact_{len(facts)}"
    facts.append(make_fact(fact_id, relation, subject, value, evidence_items, confidence, alternatives))
    return fact_id


def make_atom(line, instruction):
    atom_id = f"atom_{line.line_num}"
    atom = {
        "id": atom_id,
        "offset": line.line_num,
        "opcode": instruction["opcode"],
        "raw": instruction["raw"],
        "operands": instruction["operands"],
        "reads": instruction["reads"],
        "writes": instruction["writes"],
        "effects": instruction["effects"],
        "control_flow": instruction["control_flow"],
        "provenance": evidence(line, "v8-disassembly"),
        "semantics": [],
    }

    opcode = instruction["opcode"]
    operands = instruction["operands"]

    exact_semantics = []

    # 1. Assignments and Constants Loading
    if opcode in {"LdaSmi", "LdaSmiConstant"}:
        if operands and "value" in operands[0]:
            exact_semantics.append({
                "op": "assign",
                "dst": "ACCU",
                "src": {"kind": "immediate", "value": operands[0]["value"]}
            })
    elif opcode == "LdaZero":
        exact_semantics.append({
            "op": "assign",
            "dst": "ACCU",
            "src": {"kind": "immediate", "value": 0}
        })
    elif opcode == "LdaUndefined":
        exact_semantics.append({
            "op": "assign",
            "dst": "ACCU",
            "src": {"kind": "special", "value": "undefined"}
        })
    elif opcode == "LdaNull":
        exact_semantics.append({
            "op": "assign",
            "dst": "ACCU",
            "src": {"kind": "special", "value": "null"}
        })
    elif opcode == "LdaTheHole":
        exact_semantics.append({
            "op": "assign",
            "dst": "ACCU",
            "src": {"kind": "special", "value": "the_hole"}
        })
    elif opcode in {"Ldar", "LdarConstant"}:
        if operands:
            reg_name = operands[0].get("name") or operands[0]["text"]
            exact_semantics.append({
                "op": "assign",
                "dst": "ACCU",
                "src": {"kind": "register", "name": reg_name}
            })
    elif opcode == "Star":
        if operands:
            reg_name = operands[0].get("name") or operands[0]["text"]
            exact_semantics.append({
                "op": "assign",
                "dst": reg_name,
                "src": {"kind": "accumulator"}
            })
    elif opcode.startswith("Star") and opcode[4:].isdigit():
        reg_name = f"r{opcode[4:]}"
        exact_semantics.append({
            "op": "assign",
            "dst": reg_name,
            "src": {"kind": "accumulator"}
        })
    elif opcode == "Mov":
        if len(operands) >= 2:
            src_name = operands[0].get("name") or operands[0]["text"]
            dst_name = operands[1].get("name") or operands[1]["text"]
            exact_semantics.append({
                "op": "assign",
                "dst": dst_name,
                "src": {"kind": "register", "name": src_name}
            })

    # 2. Global and Property Accesses
    elif opcode == "LdaGlobal":
        if operands and "index" in operands[0]:
            exact_semantics.append({
                "op": "load_global",
                "dst": "ACCU",
                "index": operands[0]["index"]
            })
    elif opcode == "LdaNamedProperty":
        if len(operands) >= 2:
            obj_name = operands[0].get("name") or operands[0]["text"]
            key_name = operands[1].get("name") or operands[1]["text"]
            exact_semantics.append({
                "op": "load_property",
                "dst": "ACCU",
                "obj": obj_name,
                "key": key_name
            })
    elif opcode == "LdaKeyedProperty":
        if operands:
            obj_name = operands[0].get("name") or operands[0]["text"]
            exact_semantics.append({
                "op": "load_keyed_property",
                "dst": "ACCU",
                "obj": obj_name,
                "key": "ACCU"
            })
    elif opcode == "StaNamedProperty":
        if len(operands) >= 2:
            obj_name = operands[0].get("name") or operands[0]["text"]
            key_name = operands[1].get("name") or operands[1]["text"]
            exact_semantics.append({
                "op": "store_property",
                "obj": obj_name,
                "key": key_name,
                "val": "ACCU"
            })
    elif opcode == "StaKeyedProperty":
        if len(operands) >= 2:
            obj_name = operands[0].get("name") or operands[0]["text"]
            key_name = operands[1].get("name") or operands[1]["text"]
            exact_semantics.append({
                "op": "store_keyed_property",
                "obj": obj_name,
                "key": key_name,
                "val": "ACCU"
            })

    # 3. Arithmetic Operations
    elif opcode in {"Add", "Sub", "Mul", "Div", "Mod", "Exp", "BitwiseXor", "BitwiseOr", "BitwiseAnd", "ShiftRightLogical", "ShiftRight", "ShiftLeft"}:
        if operands:
            reg_name = operands[0].get("name") or operands[0]["text"]
            exact_semantics.append({
                "op": "binary_op",
                "operator": opcode.lower(),
                "dst": "ACCU",
                "left": "ACCU",
                "right": {"kind": "register", "name": reg_name}
            })
    elif opcode.endswith("Smi") and opcode[:-3] in {"Add", "Sub", "Mul", "Div", "Mod", "Exp", "BitwiseXor", "BitwiseOr", "BitwiseAnd", "ShiftRightLogical", "ShiftRight", "ShiftLeft"}:
        if operands and "value" in operands[0]:
            exact_semantics.append({
                "op": "binary_op",
                "operator": opcode[:-3].lower(),
                "dst": "ACCU",
                "left": "ACCU",
                "right": {"kind": "immediate", "value": operands[0]["value"]}
            })

    # 4. Unary Operations
    elif opcode == "Inc":
        exact_semantics.append({
            "op": "unary_op",
            "operator": "inc",
            "dst": "ACCU",
            "operand": "ACCU"
        })
    elif opcode == "Dec":
        exact_semantics.append({
            "op": "unary_op",
            "operator": "dec",
            "dst": "ACCU",
            "operand": "ACCU"
        })
    elif opcode == "Negate":
        exact_semantics.append({
            "op": "unary_op",
            "operator": "neg",
            "dst": "ACCU",
            "operand": "ACCU"
        })
    elif opcode == "BitwiseNot":
        exact_semantics.append({
            "op": "unary_op",
            "operator": "bit_not",
            "dst": "ACCU",
            "operand": "ACCU"
        })
    elif opcode == "LogicalNot":
        exact_semantics.append({
            "op": "unary_op",
            "operator": "log_not",
            "dst": "ACCU",
            "operand": "ACCU"
        })

    # 5. Comparison Operations
    elif opcode in {"TestEqual", "TestNotEqual", "TestLessThan", "TestGreaterThan", "TestLessThanOrEqual", "TestGreaterThanOrEqual", "TestEqualStrict", "TestInstanceOf", "TestIn"}:
        if operands:
            reg_name = operands[0].get("name") or operands[0]["text"]
            op_map = {
                "TestEqual": "eq",
                "TestNotEqual": "ne",
                "TestLessThan": "lt",
                "TestGreaterThan": "gt",
                "TestLessThanOrEqual": "le",
                "TestGreaterThanOrEqual": "ge",
                "TestEqualStrict": "eq_strict",
                "TestInstanceOf": "instanceof",
                "TestIn": "in"
            }
            exact_semantics.append({
                "op": "compare",
                "operator": op_map[opcode],
                "dst": "ACCU",
                "left": "ACCU",
                "right": {"kind": "register", "name": reg_name}
            })

    if exact_semantics:
        atom["semantics"].extend(exact_semantics)
    else:
        reads = instruction["reads"]
        writes = instruction["writes"]
        if reads["accumulator"]:
            atom["semantics"].append({"op": "acc.read", "name": "ACCU"})
        if writes["accumulator"]:
            atom["semantics"].append({"op": "acc.write", "name": "ACCU"})

        for register in reads["registers"]:
            atom["semantics"].append({"op": "reg.read", "name": register})
        for register in writes["registers"]:
            atom["semantics"].append({"op": "reg.write", "name": register})
        for const_index in reads["constants"]:
            atom["semantics"].append({"op": "const.read", "index": const_index})
        for context in reads["contexts"]:
            atom["semantics"].append({"op": "context.read", "slot": context})
        for context in writes["contexts"]:
            atom["semantics"].append({"op": "context.write", "slot": context})

        for effect in instruction["effects"]:
            atom["semantics"].append({"op": f"effect.{effect}"})

    flow = instruction["control_flow"]
    if flow["kind"] == "conditional_jump":
        atom["semantics"].append({
            "op": "branch.conditional",
            "condition": flow.get("target_condition"),
            "target": flow.get("target"),
        })
    elif flow["kind"] in {"unconditional_jump", "loop_backedge"}:
        atom["semantics"].append({"op": "branch.direct", "target": flow.get("target")})
    elif flow["kind"] == "switch":
        atom["semantics"].append({"op": "branch.switch", "targets": flow.get("targets", [])})
    elif flow["kind"] == "terminal":
        atom["semantics"].append({"op": "control.terminal"})

    return atom


def build_semantic_atoms(sfi, instructions):
    return [make_atom(line, instruction) for line, instruction in zip(sfi.code, instructions)]


def atom_by_offset(atoms):
    return {atom["offset"]: atom["id"] for atom in atoms}


def add_value_edges(edges, instruction, offset_to_atom, last_write):
    current_atom = offset_to_atom[instruction["offset"]]
    reads = instruction["reads"]
    writes = instruction["writes"]

    if reads["accumulator"] and "ACCU" in last_write:
        edges.append({"kind": "value", "from": last_write["ACCU"], "to": current_atom, "resource": "ACCU"})
    for register in reads["registers"]:
        if register in last_write:
            edges.append({"kind": "value", "from": last_write[register], "to": current_atom, "resource": register})

    if writes["accumulator"]:
        last_write["ACCU"] = current_atom
    for register in writes["registers"]:
        last_write[register] = current_atom


def is_stateful_instruction(instruction):
    if instruction["effects"]:
        return True
    if instruction["writes"]["contexts"]:
        return True
    if instruction["control_flow"]["kind"] != "fallthrough":
        return True
    return False


def build_dependence_graph(instructions, blocks, atoms):
    offset_to_atom = atom_by_offset(atoms)
    edges = []
    last_write = {}
    last_state = None

    for instruction in instructions:
        current_atom = offset_to_atom[instruction["offset"]]
        add_value_edges(edges, instruction, offset_to_atom, last_write)
        if is_stateful_instruction(instruction):
            if last_state is not None:
                edges.append({"kind": "state", "from": last_state, "to": current_atom, "resource": "v8_state"})
            last_state = current_atom

    block_start_to_atom = {
        block["start"]: offset_to_atom[block["start"]]
        for block in blocks
        if block["start"] in offset_to_atom
    }
    for block in blocks:
        from_atom = offset_to_atom.get(block["end"])
        if from_atom is None:
            continue
        for successor in block["successors"]:
            to_atom = block_start_to_atom.get(successor["target"])
            if to_atom is not None:
                edges.append({
                    "kind": "control",
                    "from": from_atom,
                    "to": to_atom,
                    "edge": successor["edge"],
                    "target": successor["target"],
                })
        for handler in block["exception_handlers"]:
            to_atom = block_start_to_atom.get(handler["catch_offset"])
            if to_atom is not None:
                edges.append({
                    "kind": "control",
                    "from": from_atom,
                    "to": to_atom,
                    "edge": "exception",
                    "target": handler["catch_offset"],
                })

    return {
        "nodes": [{"id": atom["id"], "offset": atom["offset"], "opcode": atom["opcode"]} for atom in atoms],
        "edges": edges,
    }


def expression_for_instruction(instruction):
    opcode = instruction["opcode"]
    args = [operand["text"] for operand in instruction["operands"]]
    if opcode in {"Add", "Sub", "Mul", "Div", "Mod", "Exp", "BitwiseXor", "BitwiseOr", "BitwiseAnd", "ShiftRightLogical", "ShiftRight", "ShiftLeft"} and args:
        operators = {
            "Add": "add",
            "Sub": "sub",
            "Mul": "mul",
            "Div": "div",
            "Mod": "mod",
            "Exp": "exp",
            "BitwiseXor": "xor",
            "BitwiseOr": "or",
            "BitwiseAnd": "and",
            "ShiftRightLogical": "shr_u",
            "ShiftRight": "shr_s",
            "ShiftLeft": "shl",
        }
        return {"op": operators[opcode], "args": [args[0], "ACCU"]}

    smi_match = re.match(r"^(Add|Sub|Mul|Div|Mod|Exp|BitwiseXor|BitwiseOr|BitwiseAnd|ShiftRightLogical|ShiftRight|ShiftLeft)Smi$", opcode)
    if smi_match and args:
        operators = {
            "Add": "add",
            "Sub": "sub",
            "Mul": "mul",
            "Div": "div",
            "Mod": "mod",
            "Exp": "exp",
            "BitwiseXor": "xor",
            "BitwiseOr": "or",
            "BitwiseAnd": "and",
            "ShiftRightLogical": "shr_u",
            "ShiftRight": "shr_s",
            "ShiftLeft": "shl",
        }
        value = args[0][1:] if args[0].startswith("#") else args[0]
        return {"op": operators[smi_match.group(1)], "args": ["ACCU", value]}

    if opcode == "Inc":
        return {"op": "add", "args": ["ACCU", "1"]}
    if opcode == "Dec":
        return {"op": "sub", "args": ["ACCU", "1"]}
    if opcode == "Negate":
        return {"op": "neg", "args": ["ACCU"]}
    return None


def equivalent_expressions(expression):
    if expression is None:
        return []

    op = expression["op"]
    args = expression["args"]
    alternatives = [expression]
    if op == "shl" and len(args) == 2 and args[1] == "1":
        alternatives.extend([
            {"op": "add", "args": [args[0], args[0]]},
            {"op": "mul", "args": [args[0], "2"]},
        ])
    if op == "mul" and len(args) == 2 and args[1] == "2":
        alternatives.extend([
            {"op": "add", "args": [args[0], args[0]]},
            {"op": "shl", "args": [args[0], "1"]},
        ])
    if op == "add" and len(args) == 2 and args[0] == args[1]:
        alternatives.extend([
            {"op": "mul", "args": [args[0], "2"]},
            {"op": "shl", "args": [args[0], "1"]},
        ])
    return alternatives


def build_egraph(instructions):
    classes = []
    for instruction in instructions:
        expression = expression_for_instruction(instruction)
        alternatives = equivalent_expressions(expression)
        if not alternatives:
            continue
        classes.append({
            "id": f"eclass_{len(classes)}",
            "root": f"atom_{instruction['offset']}",
            "members": alternatives,
            "constraints": {
                "language": "javascript",
                "numeric_semantics": "unknown-number-or-bigint",
                "overflow": "not-applicable-to-js-number",
            },
            "provenance": {
                "offset": instruction["offset"],
                "opcode": instruction["opcode"],
                "confidence": 0.7 if len(alternatives) > 1 else 1.0,
            },
        })
    return {"classes": classes}


def add_type_fact(facts, line, subject, type_name, reason, confidence):
    add_fact(
        facts,
        "maybe_type",
        subject,
        type_name,
        [evidence(line, "v8-bytecode-usage", confidence, reason)],
        confidence,
    )


def build_fact_store(sfi, instructions, blocks):
    facts = []
    add_fact(
        facts,
        "maybe_function",
        sfi.name,
        {
            "kind": sfi.kind,
            "argument_count": sfi.argument_count,
            "register_count": sfi.register_count,
            "declarer": sfi.declarer,
        },
        [{"source": "SharedFunctionInfo", "confidence": 1.0}],
    )

    for idx, value in enumerate(sfi.const_pool):
        alternatives = None
        if isinstance(value, str) and value.startswith("func_"):
            alternatives = [{"relation": "maybe_nested_function", "target": value, "confidence": 0.95}]
        add_fact(
            facts,
            "constant_pool_entry",
            f"ConstPool[{idx}]",
            value,
            [{"source": "ConstantPool", "index": idx, "confidence": 1.0}],
            alternatives=alternatives,
        )

    line_by_offset = {line.line_num: line for line in sfi.code}
    for instruction in instructions:
        line = line_by_offset[instruction["offset"]]
        add_fact(
            facts,
            "bytecode_instruction",
            f"offset:{instruction['offset']}",
            {"opcode": instruction["opcode"], "operands": instruction["operands"]},
            [evidence(line, "v8-disassembly")],
        )

        opcode = instruction["opcode"]
        if instruction["control_flow"]["kind"] == "loop_backedge":
            add_fact(
                facts,
                "maybe_loop",
                f"region@{instruction['control_flow'].get('target')}..{instruction['offset']}",
                {
                    "header": instruction["control_flow"].get("target"),
                    "backedge": instruction["offset"],
                },
                [evidence(line, "backedge", 0.9)],
                0.9,
            )
        if opcode.startswith("JumpIf"):
            add_type_fact(facts, line, "ACCU", "maybe_boolean_or_truthy", "conditional jump consumes accumulator", 0.65)
        if opcode.startswith(("Add", "Sub", "Mul", "Div", "Mod", "Exp", "Bitwise", "Shift")) or opcode in {"Inc", "Dec", "Negate"}:
            add_type_fact(facts, line, "ACCU", "maybe_number", "arithmetic opcode", 0.7)
        if opcode.startswith(("LdaNamedProperty", "GetNamedProperty", "SetNamedProperty", "StaNamedProperty", "DefineNamedOwnProperty")):
            add_type_fact(facts, line, "receiver", "maybe_object", "named property access", 0.7)
        if opcode.startswith("Call") or opcode == "InvokeIntrinsic":
            add_fact(
                facts,
                "maybe_call",
                f"offset:{instruction['offset']}",
                {"target": instruction["operands"][0] if instruction["operands"] else None},
                [evidence(line, "call-opcode", 0.85)],
                0.85,
            )

    for block in blocks:
        for handler in block["exception_handlers"]:
            add_fact(
                facts,
                "maybe_exception_region",
                f"{block['id']}->{handler['block']}",
                handler,
                [{"source": "HandlerTable", "confidence": 0.9}],
                0.9,
            )

    return {"facts": facts}


def build_region_candidates(blocks):
    regions = []
    for block in blocks:
        for successor in block["successors"]:
            if successor["target"] <= block["start"]:
                regions.append({
                    "id": f"region_{len(regions)}",
                    "kind": "loop_candidate",
                    "header": successor["target"],
                    "latch": block["end"],
                    "blocks": sorted({block["id"], successor["block"]}),
                    "confidence": 0.8,
                    "evidence": [{"source": "control_backedge", "edge": successor["edge"]}],
                })
            elif successor["edge"] not in {"fallthrough", "jump", "backedge"}:
                regions.append({
                    "id": f"region_{len(regions)}",
                    "kind": "branch_candidate",
                    "condition_edge": successor["edge"],
                    "entry": block["id"],
                    "target": successor["block"],
                    "confidence": 0.65,
                    "evidence": [{"source": "conditional_successor"}],
                })
        if block["exception_handlers"]:
            regions.append({
                "id": f"region_{len(regions)}",
                "kind": "exception_candidate",
                "try_block": block["id"],
                "handlers": block["exception_handlers"],
                "confidence": 0.9,
                "evidence": [{"source": "HandlerTable"}],
            })
    return regions


def build_type_hypotheses(fact_store):
    return [fact for fact in fact_store["facts"] if fact["relation"] == "maybe_type"]


def build_high_level_candidates(fact_store):
    return [
        fact for fact in fact_store["facts"]
        if fact["relation"] in {"maybe_loop", "maybe_exception_region", "maybe_call", "maybe_function"}
    ]


def lift_function(sfi):
    instructions = [lift_instruction(line) for line in sfi.code]
    blocks = build_basic_blocks(instructions, sfi.exception_table)
    atoms = build_semantic_atoms(sfi, instructions)
    fact_store = build_fact_store(sfi, instructions, blocks)
    dependence_graph = build_dependence_graph(instructions, blocks, atoms)
    egraph = build_egraph(instructions)
    return {
        "schema": SCHEMA_VERSION,
        "name": sfi.name,
        "kind": sfi.kind,
        "declarer": sfi.declarer,
        "argument_count": sfi.argument_count,
        "register_count": sfi.register_count,
        "constant_pool": list(sfi.const_pool),
        "exception_table": {
            str(catch_start): try_range for catch_start, try_range in sfi.exception_table.items()
        },
        "semantic_atoms": atoms,
        "fact_store": fact_store,
        "dependence_graph": dependence_graph,
        "egraph": egraph,
        "region_candidates": build_region_candidates(blocks),
        "type_hypotheses": build_type_hypotheses(fact_store),
        "high_level_candidates": build_high_level_candidates(fact_store),
        "blocks": blocks,
    }
