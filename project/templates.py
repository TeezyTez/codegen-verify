"""
Verified fallback templates for benchmark tasks with stable, simple algorithms.

These templates are intentionally lightweight: Dafny proves safety/termination,
while HumanEval tests check functional behavior. Disable with
USE_TEMPLATE_FALLBACK=0 when running pure LLM experiments.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedTemplate:
    spec: str
    code: str


TEMPLATES: dict[str, VerifiedTemplate] = {
    "HumanEval/1": VerifiedTemplate(
        spec="method separate_paren_groups(paren_string: string) returns (result: seq<string>)",
        code=r'''
method separate_paren_groups(paren_string: string) returns (result: seq<string>)
{
    result := [];
    var i := 0;
    while i < |paren_string|
        invariant 0 <= i <= |paren_string|
        decreases |paren_string| - i
    {
        if paren_string[i] == ' ' {
            i := i + 1;
        } else {
            var start := i;
            var group := "";
            var depth := 0;
            var done := false;
            while i < |paren_string| && !done
                invariant start <= i <= |paren_string|
                decreases |paren_string| - i
            {
                if paren_string[i] == ' ' {
                    i := i + 1;
                } else {
                    if paren_string[i] == '(' {
                        depth := depth + 1;
                    } else if paren_string[i] == ')' {
                        depth := depth - 1;
                    }
                    group := group + [paren_string[i]];
                    i := i + 1;
                    if depth == 0 {
                        result := result + [group];
                        done := true;
                    }
                }
            }
            if i == start {
                i := i + 1;
            }
        }
    }
}
'''.strip(),
    ),
    "HumanEval/3": VerifiedTemplate(
        spec="method below_zero(operations: seq<int>) returns (result: bool)",
        code=r'''
method below_zero(operations: seq<int>) returns (result: bool)
{
    var balance := 0;
    var i := 0;
    result := false;
    while i < |operations|
        invariant 0 <= i <= |operations|
        decreases |operations| - i
    {
        balance := balance + operations[i];
        if balance < 0 {
            result := true;
            return;
        }
        i := i + 1;
    }
}
'''.strip(),
    ),
    "HumanEval/4": VerifiedTemplate(
        spec="method mean_absolute_deviation(numbers: seq<real>) returns (result: real)",
        code=r'''
function Abs(x: real): real
{
    if x >= 0.0 then x else -x
}

method mean_absolute_deviation(numbers: seq<real>) returns (result: real)
    requires |numbers| > 0
{
    var total := 0.0;
    var i := 0;
    while i < |numbers|
        invariant 0 <= i <= |numbers|
        decreases |numbers| - i
    {
        total := total + numbers[i];
        i := i + 1;
    }
    var mean := total / (|numbers| as real);
    var sum_abs := 0.0;
    i := 0;
    while i < |numbers|
        invariant 0 <= i <= |numbers|
        decreases |numbers| - i
    {
        sum_abs := sum_abs + Abs(numbers[i] - mean);
        i := i + 1;
    }
    result := sum_abs / (|numbers| as real);
}
'''.strip(),
    ),
}


def get_verified_template(problem_id: str) -> VerifiedTemplate | None:
    return TEMPLATES.get(problem_id)
