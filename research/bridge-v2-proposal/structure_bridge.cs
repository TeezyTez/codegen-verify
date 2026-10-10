using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text;
using System.Threading.Tasks;

// Actual Dafny AST inspection, hosted by PowerShell Core. No candidate text is
// compiled as C# and no candidate controls assembly loading or compiler options.
public static class PublicDafnyStructure {
  static object Get(object obj, string name) {
    if (obj == null) return null;
    for (var t = obj.GetType(); t != null; t = t.BaseType) {
      var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
      if (p != null) return p.GetValue(obj);
      var f = t.GetField(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
      if (f != null) return f.GetValue(obj);
    }
    return null;
  }
  static IEnumerable<object> Items(object value) {
    if (value is IEnumerable sequence) foreach (object item in sequence) if (item != null) yield return item;
  }
  static string Text(object value) { return value == null ? "" : value.ToString(); }
  static bool Is(object node, string name) {
    for (var t = node?.GetType(); t != null; t = t.BaseType)
      if (t.FullName == "Microsoft.Dafny." + name) return true;
    return false;
  }
  static IEnumerable<object> Walk(object root, bool resolved) {
    var visited = new HashSet<object>(ReferenceEqualityComparer.Instance);
    var pending = new Stack<object>(); pending.Push(root);
    while (pending.Count != 0) {
      var node = pending.Pop();
      if (node == null || !visited.Add(node)) continue;
      yield return node;
      foreach (var child in Items(Get(node, resolved ? "Children" : "PreResolveChildren"))) pending.Push(child);
    }
  }
  static int Pos(object token) { return Convert.ToInt32(Get(token, "pos")); }
  static int Start(object node) { return Pos(Get(node, "StartToken")); }
  static int End(object node) { var tok = Get(node, "EndToken"); return Pos(tok) + Encoding.UTF8.GetByteCount(Text(Get(tok, "val"))); }
  static int[] Utf8ToUtf16Map(string source) {
    var positions = new int[Encoding.UTF8.GetByteCount(source) + 1];
    Array.Fill(positions, -1);
    int bytes = 0, chars = 0;
    foreach (var rune in source.EnumerateRunes()) {
      positions[bytes] = chars;
      bytes += rune.Utf8SequenceLength;
      chars += rune.Utf16SequenceLength;
    }
    positions[bytes] = chars;
    return positions;
  }
  static int Utf16Offset(int[] positions, int byteOffset) {
    if (byteOffset < 0 || byteOffset >= positions.Length || positions[byteOffset] < 0)
      throw new InvalidOperationException("Compiler token is not on a UTF-8 boundary");
    return positions[byteOffset];
  }
  static string Id(object node) { return Text(Get(node, "FullDafnyName")); }
  static string[] Tokens(object node, int before = int.MaxValue) {
    return Items(Get(node, "CoveredTokens")).Where(t => Pos(t) < before).Select(t => Text(Get(t, "val"))).ToArray();
  }
  static Dictionary<string, object> Finding(string code, string message, string decl = null) {
    return new Dictionary<string, object> { ["code"] = code, ["message"] = message, ["declaration"] = decl };
  }
  static object Ref(object node) {
    if (Is(node, "FunctionCallExpr")) return Get(node, "Function");
    if (Is(node, "CallStmt")) return Get(node, "Method") ?? Get(Get(node, "MethodSelect"), "Member");
    if (Is(node, "MemberSelectExpr")) return Get(node, "Member");
    return null;
  }
  static object Await(object task) {
    ((Task)task).GetAwaiter().GetResult(); return Get(task, "Result");
  }
  public static string Inspect(string home, string source) {
    var findings = new List<Dictionary<string, object>>();
    var declarations = new List<Dictionary<string, object>>();
    var result = new Dictionary<string, object> {
      ["schema_version"] = 1, ["status"] = "tool_error", ["trusted_ast"] = false,
      ["bridge_runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
      ["declarations"] = declarations, ["findings"] = findings,
      ["expected_verifier_targets"] = Array.Empty<string>()
    };
    try {
      var core = Assembly.LoadFrom(Path.Combine(home, "DafnyCore.dll"));
      Func<string, Type> type = name => core.GetType("Microsoft.Dafny." + name, true);
      var output = new StringWriter();
      var options = Activator.CreateInstance(type("DafnyOptions"), new object[] {new StringReader(""), output, output});
      type("DafnyOptions").GetMethod("ApplyDefaultOptions").Invoke(options, null);
      var shadow = type("CommonOptionBag").GetField("WarnShadowing").GetValue(null);
      type("DafnyOptions").GetMethod("SetUntyped").Invoke(options, new object[] {shadow, true});
      var reporter = Activator.CreateInstance(type("BatchErrorReporter"), options);
      var parsed = Await(type("ProgramParser").GetMethod("Parse").Invoke(null,
        new object[] {source, new Uri("file:///candidate.dfy"), reporter}));
      var program = Get(parsed, "Program");
      Action diagnostics = () => {
        foreach (var message in Items(Get(reporter, "AllMessages")))
          findings.Add(Finding("compiler_diagnostic", Text(Get(message, "Message"))));
      };
      if (Convert.ToInt32(Get(reporter, "ErrorCount")) != 0) {
        result["status"] = "parse_error"; diagnostics(); return JsonSerializer.Serialize(result);
      }
      result["trusted_ast"] = true;
      var positions = Utf8ToUtf16Map(source);
      var module = Get(program, "DefaultModuleDef");
      var members = new List<object>();
      var sourceContracts = new List<Dictionary<string, object[]>>();
      foreach (var top in Items(Get(module, "TopLevelDecls"))) {
        if (!Is(top, "DefaultClassDecl")) {
          findings.Add(Finding("unsupported_declaration", top.GetType().Name)); continue;
        }
        foreach (var member in Items(Get(top, "Members"))) {
          if (!(Is(member, "Method") || Is(member, "Function")) ||
              Is(member, "ExtremeLemma") || Is(member, "ExtremePredicate")) {
            findings.Add(Finding("unsupported_declaration", member.GetType().Name)); continue;
          }
          members.Add(member);
        }
      }
      foreach (var node in Walk(program, false)) {
        var kind = node.GetType().Name;
        if (Get(node, "Attributes") != null || Is(node, "Attributes"))
          findings.Add(Finding("attribute", "Source attributes are not allowed: " + kind));
        // expect is also an assumption to the verifier (checked only at runtime).
        if (Is(node, "AssumeStmt") || Is(node, "ExpectStmt") || (Is(node, "AssignSuchThatStmt") && Get(node, "AssumeToken") != null))
          findings.Add(Finding("assume", "Assumption node: " + kind));
        if (Is(node, "WildcardExpr") && !(Is(node, "FrameExpression")))
          findings.Add(Finding("nontermination", "Wildcard decreases/reads are unsupported."));
        if ((Is(node, "Method") || Is(node, "Function") || Is(node, "WhileStmt") || Is(node, "ForLoopStmt") || Is(node, "ForallStmt")) && Get(node, "Body") == null)
          findings.Add(Finding("missing_body", "Missing body: " + kind));
        if (Is(node, "Function") && Get(node, "ByMethodBody") != null)
          findings.Add(Finding("unsupported_declaration", "Function-by-method needs separate coverage and is not supported."));
      }
      // Snapshot all source syntax before resolver inserts inferred contracts.
      foreach (var member in members) {
        var body = Get(member, "Body");
        var bodyToken = Get(member, "BodyStartTok");
        int rawStart = Start(member), rawEnd = End(member);
        int rawBodyStart = bodyToken == null ? rawEnd : Pos(bodyToken);
        int start = Utf16Offset(positions, rawStart), end = Utf16Offset(positions, rawEnd);
        int bodyStart = Utf16Offset(positions, rawBodyStart);
        if (start < 0 || bodyStart < start || end < bodyStart || end > source.Length)
          throw new InvalidOperationException("Invalid AST source region");
        var contracts = new Dictionary<string, object[]>();
        foreach (var field in new string[] {"Req", "Ens", "Reads", "Mod", "Decreases"}) {
          var value = Get(member, field);
          contracts[field] = Items(value is IEnumerable ? value : Get(value, "Expressions")).ToArray();
        }
        sourceContracts.Add(contracts);
        var signatureMethod = Is(member, "Function") ? "FunctionSignatureToString" : "MethodSignatureToString";
        declarations.Add(new Dictionary<string, object> {
          ["id"] = Text(Get(member, "Name")), ["name"] = Text(Get(member, "Name")),
          ["kind"] = Text(Get(member, "WhatKind")), ["ast_kind"] = member.GetType().Name,
          ["header"] = source.Substring(start, bodyStart-start),
          ["body"] = body == null ? null : source.Substring(bodyStart, end-bodyStart),
          ["source_region"] = new int[] {start, end}, ["body_region"] = new int[] {bodyStart, end},
          ["tokens"] = Tokens(member), ["header_tokens"] = Tokens(member, rawBodyStart),
          ["depends_on"] = Array.Empty<string>(), ["unresolved_dependencies"] = Array.Empty<string>(),
          ["verifier_names"] = new string[] {Text(Get(member, "Name"))},
          ["signature"] = type("Printer").GetMethod(signatureMethod).Invoke(null, new object[] {options, member}),
          ["contracts"] = contracts.ToDictionary(pair => pair.Key, pair => pair.Value.Select(e => string.Join(" ", Tokens(e))).ToArray()),
        });
      }
      if (findings.Count != 0) { result["status"] = "rejected"; return JsonSerializer.Serialize(result); }
      var resolveError = type("DafnyMain").GetMethod("Resolve").Invoke(null, new object[] {program});
      if (resolveError != null || Convert.ToInt32(Get(reporter, "ErrorCount")) != 0) {
        result["status"] = "resolution_error"; diagnostics(); return JsonSerializer.Serialize(result);
      }
      if (Convert.ToInt32(Get(reporter, "WarningCount")) != 0) {
        result["status"] = "rejected"; diagnostics(); return JsonSerializer.Serialize(result);
      }
      var names = new HashSet<string>(members.Select(Id), StringComparer.Ordinal);
      var systemModule = Get(Get(program, "SystemModuleManager"), "SystemModule");
      for (int i = 0; i < members.Count; i++) {
        var member = members[i]; var d = declarations[i]; var id = Id(member);
        d["id"] = id; d["verifier_names"] = new string[] {id};
        var dependencies = new SortedSet<string>(StringComparer.Ordinal);
        var unresolved = new SortedSet<string>(StringComparer.Ordinal);
        var builtins = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var node in Walk(member, true)) {
          var reference = Ref(node);
          if (reference != null) {
            var target = Id(reference);
            if (names.Contains(target)) dependencies.Add(target);
            else if (ReferenceEquals(Get(Get(reference, "EnclosingClass"), "EnclosingModuleDefinition"), systemModule)) builtins.Add(target);
            else unresolved.Add(target.Length == 0 ? reference.GetType().Name : target);
          }
          if (Is(node, "ApplyExpr")) findings.Add(Finding("unsupported_dependency", "Higher-order application", id));
        }
        d["depends_on"] = dependencies.ToArray(); d["unresolved_dependencies"] = unresolved.ToArray();
        d["builtin_references"] = builtins.ToArray();
        if (unresolved.Count != 0) findings.Add(Finding("unsupported_dependency", "Unmapped declaration reference", id));
        var bindings = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var field in sourceContracts[i].Keys) {
          var expressions = sourceContracts[i][field];
          foreach (var expression in expressions) foreach (var node in Walk(expression, true)) {
            var reference = Ref(node);
            if (reference != null) bindings.Add(field + ":member:" + Id(reference));
            if (Is(node, "IdentifierExpr")) {
              var variable = Get(node, "Var");
              bindings.Add(field + ":variable:" + variable?.GetType().Name + ":" + Text(Get(variable, "Name")));
            }
          }
        }
        d["contract_bindings"] = bindings.ToArray();
      }
      result["expected_verifier_targets"] = declarations.Select(d => (string)d["id"]).ToArray();
      result["status"] = findings.Count == 0 ? "ok" : "rejected";
    } catch (Exception error) {
      result["status"] = "tool_error"; result["trusted_ast"] = false;
      findings.Add(Finding("bridge_failed", error.ToString()));
    }
    return JsonSerializer.Serialize(result);
  }
}
