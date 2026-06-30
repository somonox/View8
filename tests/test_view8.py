import unittest
import os
import sys
import json
from jsonschema import validate, ValidationError

# Add repository root to the path so we can import View8 modules.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Parser.v8_version import version_hash64, hash_value_unsigned, hash_combine64
from Parser.parse_v8cache import parse_disassembled_file
from IR.v8_lifter import SCHEMA_VERSION


class TestVersionDetector(unittest.TestCase):
    def test_hash_value_unsigned(self):
        # Basic sanity check for hash value calculations
        val = hash_value_unsigned(0)
        self.assertIsInstance(val, int)
        self.assertTrue(0 <= val <= 0xFFFFFFFF)

        val_24 = hash_value_unsigned(24)
        self.assertIsInstance(val_24, int)
        self.assertTrue(0 <= val_24 <= 0xFFFFFFFF)

    def test_version_hash64(self):
        # Test hash matching for specific V8 version (9.4.146.24)
        h = version_hash64(9, 4, 146, 24)
        self.assertIsInstance(h, int)
        self.assertTrue(0 <= h <= 0xFFFFFFFF)

        # Test order independence/uniqueness
        h2 = version_hash64(9, 4, 146, 0)
        self.assertNotEqual(h, h2)


class TestSnirFixtureAndSchema(unittest.TestCase):
    def setUp(self):
        self.workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.fixture_path = os.path.join(self.workspace_dir, 'view8_snir_sample.disasm')
        self.schema_path = os.path.join(self.workspace_dir, 'IR/snir_schema.json')

    def test_snir_lifter_and_json_schema(self):
        # Ensure the fixture exists
        self.assertTrue(os.path.isfile(self.fixture_path), f"Fixture not found at {self.fixture_path}")
        self.assertTrue(os.path.isfile(self.schema_path), f"Schema not found at {self.schema_path}")

        # Parse disassembly using the parser
        all_funcs = parse_disassembled_file(self.fixture_path)
        self.assertIn('func_start_0', all_funcs)

        # Lift IR for func_start_0
        func_obj = all_funcs['func_start_0']
        lifted_ir = func_obj.lift_ir()

        # Validate general lifted properties
        self.assertEqual(lifted_ir["schema"], SCHEMA_VERSION)
        self.assertEqual(lifted_ir["name"], "func_start_0")
        self.assertEqual(lifted_ir["kind"], "NormalFunction")
        self.assertEqual(lifted_ir["argument_count"], 2)
        self.assertEqual(lifted_ir["register_count"], 2)

        # Verify that exact semantic atoms for assignments/constants were populated
        # Ldar a0 (offset 0)
        ldar_atom = lifted_ir["semantic_atoms"][0]
        self.assertEqual(ldar_atom["opcode"], "Ldar")
        self.assertTrue(any(op["op"] == "assign" and op["dst"] == "ACCU" and op["src"]["kind"] == "register" for op in ldar_atom["semantics"]))

        # Star0 (offset 1) -> assign dst: r0
        star_atom = lifted_ir["semantic_atoms"][1]
        self.assertEqual(star_atom["opcode"], "Star0")
        self.assertTrue(any(op["op"] == "assign" and op["dst"] == "r0" and op["src"]["kind"] == "accumulator" for op in star_atom["semantics"]))

        # LdaSmi #2 (offset 2) -> assign dst: ACCU, immediate value: 2
        ldasmi_atom = lifted_ir["semantic_atoms"][2]
        self.assertEqual(ldasmi_atom["opcode"], "LdaSmi")
        self.assertTrue(any(op["op"] == "assign" and op["dst"] == "ACCU" and op["src"]["value"] == 2 for op in ldasmi_atom["semantics"]))

        # Mul r0 (offset 3) -> binary_op operator: mul
        mul_atom = lifted_ir["semantic_atoms"][3]
        self.assertEqual(mul_atom["opcode"], "Mul")
        self.assertTrue(any(op["op"] == "binary_op" and op["operator"] == "mul" for op in mul_atom["semantics"]))

        # Build complete document structure to match schema
        document = {
            "schema": "view8-snir-document-v1",
            "functions": [lifted_ir]
        }

        # Validate against JSON Schema
        with open(self.schema_path, 'r') as f:
            schema = json.load(f)

        try:
            validate(instance=document, schema=schema)
        except ValidationError as e:
            self.fail(f"JSON Schema validation failed: {e.message}")


class TestCommandLineArgs(unittest.TestCase):
    def setUp(self):
        self.workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.view8_script = os.path.join(self.workspace_dir, 'view8.py')
        self.fixture_path = os.path.join(self.workspace_dir, 'view8_snir_sample.disasm')
        self.output_path = os.path.join(self.workspace_dir, 'test_output_snir.json')

    def tearDown(self):
        if os.path.isfile(self.output_path):
            os.remove(self.output_path)

    def test_ir_alias_export(self):
        # Run view8.py with -e ir to verify compatibility alias
        import subprocess
        python_bin = sys.executable
        cmd = [python_bin, self.view8_script, self.fixture_path, self.output_path, "--disassembled", "-e", "ir"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Execution failed: {result.stderr}")

        # Check output file
        self.assertTrue(os.path.isfile(self.output_path))
        with open(self.output_path, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(data["schema"], "view8-snir-document-v1")
        self.assertIn("functions", data)
        self.assertEqual(len(data["functions"]), 1)

    def test_snir_json_to_js_decompilation(self):
        # Run view8.py to generate SNIR json
        import subprocess
        python_bin = sys.executable
        cmd_gen = [python_bin, self.view8_script, self.fixture_path, self.output_path, "--disassembled", "-e", "snir"]
        result_gen = subprocess.run(cmd_gen, capture_output=True, text=True)
        self.assertEqual(result_gen.returncode, 0, f"SNIR generation failed: {result_gen.stderr}")

        # Run view8.py on the SNIR json file to decompile back to js
        js_out_path = os.path.join(self.workspace_dir, 'test_decompiled.js')
        if os.path.isfile(js_out_path):
            os.remove(js_out_path)

        try:
            cmd_dec = [python_bin, self.view8_script, self.output_path, js_out_path, "-e", "decompiled"]
            result_dec = subprocess.run(cmd_dec, capture_output=True, text=True)
            self.assertEqual(result_dec.returncode, 0, f"Decompilation from SNIR failed: {result_dec.stderr}")
            self.assertTrue(os.path.isfile(js_out_path))

            with open(js_out_path, 'r') as f:
                content = f.read()
            self.assertIn("function func_start_0(a0)", content)
            self.assertIn("r1 = (r0 * 2)", content)
            self.assertIn("return (r1 + 1)", content)
        finally:
            if os.path.isfile(js_out_path):
                os.remove(js_out_path)


if __name__ == '__main__':
    unittest.main()
