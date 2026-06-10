"""internal-ax: agent-readiness tester.

Measures, for a given input prompt, whether a target tool is:
  1. discovered/recommended by a bare LLM call (training knowledge only),
  2. discovered/recommended by an LLM with web search + reasoning,
  3. discovered, recommended AND correctly used by a code agent (Claude Code, Codex).

Triggered by Langfuse remote dataset runs, executed headlessly on Modal,
traced back to Langfuse.
"""

__version__ = "0.1.0"
