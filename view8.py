import argparse
import json
import os
from Parser.parse_v8cache import parse_v8cache_file, parse_disassembled_file
from Parser.shared_function_info import SharedFunctionInfo, CodeLine
from Simplify.global_scope_replace import replace_global_scope



def disassemble(in_file, input_is_disassembled, disassembler):
    out_name = 'disasm.tmp'
    view8_dir = os.path.dirname(os.path.abspath(__file__))
    
    if input_is_disassembled:
        out_name = in_file
    else:
        # Disassemble the file
        parse_v8cache_file(in_file, out_name, view8_dir, disassembler)
    
    return parse_disassembled_file(out_name)


def parse_snir_json_file(in_file):
    print(f"Parsing SNIR JSON file: {in_file}")
    with open(in_file, 'r') as f:
        doc = json.load(f)

    if doc.get("schema") != "view8-snir-document-v1":
        raise ValueError(f"Unsupported SNIR document schema: {doc.get('schema')}")

    all_functions = {}
    for func_data in doc.get("functions", []):
        sfi = SharedFunctionInfo()
        sfi.name = func_data["name"]
        sfi.kind = func_data["kind"]
        sfi.declarer = func_data["declarer"]
        sfi.argument_count = func_data["argument_count"]
        sfi.register_count = func_data["register_count"]
        sfi.const_pool = func_data["constant_pool"]
        sfi.exception_table = {int(k): v for k, v in func_data["exception_table"].items()}

        code_lines = []
        for atom in func_data["semantic_atoms"]:
            code_lines.append(
                CodeLine(
                    opcode="",
                    line=atom["offset"],
                    inst=atom["raw"]
                )
            )
        sfi.code = code_lines
        all_functions[sfi.name] = sfi

    print(f"Successfully loaded {len(all_functions)} functions from SNIR JSON.")
    return all_functions



def decompile(all_functions, nested):
    # Decompile
    print(f"Decompiling {len(all_functions)} functions.")
    if nested:
        for name in list(all_functions):
            all_functions[name].const_functions = {const: all_functions[const] for const in all_functions[name].const_pool if const.startswith('func_')}
    for name in list(all_functions)[::-1]:
        if not nested or all_functions[name].declarer is None:
            all_functions[name].decompile(nested)
    # replace_global_scope(all_functions)


def export_to_file(out_name, all_functions, format_list, nested):
    print(f"Exporting to file {out_name}.")
    if "snir" in format_list or "ir" in format_list:
        export_ir_to_file(out_name, all_functions, nested)
        return

    with open(out_name, "w") as f:
        for function_name in list(all_functions)[::-1]:
            if not nested or all_functions[function_name].declarer is None:
                f.write(all_functions[function_name].export(export_v8code="v8_opcode" in format_list, export_translated="translated" in format_list, export_decompiled="decompiled" in format_list, nested=nested))


def export_ir_to_file(out_name, all_functions, nested):
    functions = []
    for function_name in list(all_functions)[::-1]:
        if not nested or all_functions[function_name].declarer is None:
            functions.append(all_functions[function_name].lift_ir())

    document = {
        "schema": "view8-snir-document-v1",
        "functions": functions,
    }
    with open(out_name, "w") as f:
        json.dump(document, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="View8: V8 cache decompiler.")
    parser.add_argument('input_file', help="The input file name.")
    parser.add_argument('output_file', help="The output file name.")
    parser.add_argument('--path', '-p', help="Path to disassembler binary.", default=None)
    parser.add_argument('--disassembled', '-d', action='store_true', help="Indicate if the input file is already disassembled.")
    parser.add_argument('--export_format', '-e', nargs='+', choices=['v8_opcode', 'translated', 'decompiled', 'snir', 'ir'], 
                        help="Specify the export format(s). Options are 'v8_opcode', 'translated', 'decompiled', and 'snir'. Multiple text formats can be combined. The 'snir' format exports a JSON SNIR document. 'ir' is kept as a compatibility alias.", 
                        default=['decompiled'])
    parser.add_argument('--nested', '-n', action='store_true', help="Export nested format.", default=False)

    args = parser.parse_args()
    
    if not os.path.isfile(args.input_file):
        raise FileNotFoundError(f"The input file {args.input_file} does not exist.")

    if args.input_file.endswith('.json'):
        all_func = parse_snir_json_file(args.input_file)
    else:
        all_func = disassemble(args.input_file, args.disassembled, args.path)
    if any(format_name not in {"snir", "ir"} for format_name in args.export_format):
        decompile(all_func, args.nested)
    export_to_file(args.output_file, all_func, args.export_format, args.nested)
    print(f"Done.")


if __name__ == "__main__":
    main()
