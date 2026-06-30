#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "include/v8.h"
#include "include/libplatform/libplatform.h"

using namespace v8;

static Isolate* isolate = nullptr;

// Compatibility with v8 versions that have different ScriptOrigin constructors
template <typename... Args>
ScriptOrigin CreateScriptOrigin(Args&&... args) {
  if constexpr (std::is_constructible_v<ScriptOrigin, Isolate*, Local<String>>) {
      return ScriptOrigin(isolate, std::forward<Args>(args)...);
  } else {
      return ScriptOrigin(std::forward<Args>(args)...);
  }
}

static void loadBytecode(uint8_t* bytecodeBuffer, int length) {
  // Load code into code cache.
  ScriptCompiler::CachedData* cached_data =
      new ScriptCompiler::CachedData(bytecodeBuffer, length);

  // Create dummy source.
  ScriptOrigin origin = CreateScriptOrigin(String::NewFromUtf8Literal(isolate, "code.jsc"));

  ScriptCompiler::Source source(String::NewFromUtf8Literal(isolate, "\"ಠ_ಠ\""),
                                origin, cached_data);

  // Compile code from code cache to print disassembly.
  MaybeLocal<UnboundScript> script = ScriptCompiler::CompileUnboundScript(
      isolate, &source, ScriptCompiler::kConsumeCodeCache);
}

static void readAllBytes(const std::string& file, std::vector<char>& buffer) {
  std::ifstream infile(file, std::ios::binary);

  infile.seekg(0, infile.end);
  size_t length = infile.tellg();
  infile.seekg(0, infile.beg);

  if (length > 0) {
    buffer.resize(length);
    infile.read(&buffer[0], length);
  }
}

static std::string readText(const std::string& file) {
  std::ifstream infile(file, std::ios::binary);
  return std::string(std::istreambuf_iterator<char>(infile),
                     std::istreambuf_iterator<char>());
}

static void writeAllBytes(const std::string& file, const uint8_t* data, int length) {
  std::ofstream outfile(file, std::ios::binary);
  outfile.write(reinterpret_cast<const char*>(data), length);
}

static void compileToBytecode(const std::string& inputFile, const std::string& outputFile) {
  std::string sourceText = readText(inputFile);
  Local<String> sourceString =
      String::NewFromUtf8(isolate, sourceText.c_str(), NewStringType::kNormal,
                          static_cast<int>(sourceText.size())).ToLocalChecked();
  ScriptOrigin origin = CreateScriptOrigin(
      String::NewFromUtf8(isolate, inputFile.c_str(), NewStringType::kNormal).ToLocalChecked());
  ScriptCompiler::Source source(sourceString, origin);

  Local<UnboundScript> script;
  if (!ScriptCompiler::CompileUnboundScript(isolate, &source, ScriptCompiler::kNoCompileOptions)
           .ToLocal(&script)) {
    throw std::runtime_error("Failed to compile JavaScript source.");
  }

  std::unique_ptr<ScriptCompiler::CachedData> cachedData(
      ScriptCompiler::CreateCodeCache(script));
  if (!cachedData || !cachedData->data || cachedData->length <= 0) {
    throw std::runtime_error("Failed to create V8 code cache.");
  }

  writeAllBytes(outputFile, cachedData->data, cachedData->length);
}

int main(int argc, char* argv[]) {
  if (argc < 2) {
    std::cerr << "Usage:\n"
              << "  " << argv[0] << " input.jsc\n"
              << "  " << argv[0] << " --compile input.js output.jsc\n";
    return 1;
  }

  V8::SetFlagsFromString("--no-lazy --no-flush-bytecode");

  V8::InitializeICU();
  std::unique_ptr<Platform> platform = platform::NewDefaultPlatform();
  V8::InitializePlatform(platform.get());
  V8::Initialize();

  Isolate::CreateParams create_params;
  create_params.array_buffer_allocator =
      ArrayBuffer::Allocator::NewDefaultAllocator();

  isolate = Isolate::New(create_params);
  Isolate::Scope isolate_scope(isolate);
  HandleScope handle_scope(isolate);
  Local<v8::Context> context = Context::New(isolate);
  Context::Scope context_scope(context);

  try {
    if (std::string(argv[1]) == "--compile") {
      if (argc != 4) {
        throw std::runtime_error("--compile requires input.js and output.jsc.");
      }
      compileToBytecode(argv[2], argv[3]);
      return 0;
    }

    std::vector<char> data;
    readAllBytes(argv[1], data);
    loadBytecode((uint8_t*)data.data(), data.size());
  } catch (const std::exception& error) {
    std::cerr << error.what() << "\n";
    return 1;
  }
}
