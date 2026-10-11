# Writing Good CL Descriptions

Source: https://google.github.io/eng-practices/review/developer/cl-descriptions.html

A CL description is a permanent public record. It must communicate:

1. **What** change is being made, summarized so readers understand it without reading the whole CL.
2. **Why** it is being made: the context, and any decisions not visible in the code.

Future developers search for CLs by description, and need the why to judge whether a decision (Chesterton's fence) can be changed.

## First line

- A short summary of what the CL does.
- A complete sentence written as an imperative order ("Delete the FizzBuzz RPC and replace it with the new system." not "Deleting ... and replacing ...").
- Followed by a blank line.

It should stand alone so people can skim history. Keep it short, focused, and clear.

## Body

Fill in the details: the problem being solved, why this approach is best, known shortcomings, and relevant background such as bug numbers, benchmark results, and design docs. External links may become inaccessible, so include enough context to stand alone.

Even small CLs deserve detail.

## Bad descriptions

"Fix bug", "Fix build.", "Add patch.", "Moving code from A to B.", "Phase 1.", "Add convenience functions.", "kill weird URLs."

These say neither what was fixed nor why.

## Good examples

**Functionality change**

> RPC: Remove size limit on RPC server message freelist.
>
> Servers like FizzBuzz have very large messages and would benefit from reuse. Make the freelist larger, and add a goroutine that frees the freelist entries slowly over time, so that idle servers eventually release all freelist entries.

**Refactoring**

> Construct a Task with a TimeKeeper to use its TimeStr and Now methods.
>
> Add a Now method to Task, so the borglet() getter method can be removed. ...
>
> Allowing Tasks to supply Now is a step toward eliminating the dependency on Borglet. ...

**Small CL needing context**

> Create a Python3 build rule for status.py.
>
> This allows consumers who are already using this as in Python3 to depend on a rule next to the original status build rule. It encourages new consumers to use Python3 and simplifies some automated refactoring tools.

## Tags

Tags such as `[tag]`, `#tag`, or `tag:` are optional. Keep them short. Prefer putting them in the body. Avoid long tags in the first line.

## Generated descriptions

Tool-generated CLs should follow the same guidance: short, standalone first line and an informative body.

## Review before submitting

CLs change during review. Check that the description still matches what the CL does before submitting.
