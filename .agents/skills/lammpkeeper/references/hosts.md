# Host integration

Repository author: Kim Donghwan.

The canonical skill is `.agents/skills/lammpkeeper/SKILL.md`. Keep its frontmatter portable: `name`, `description`, and `compatibility`; do not add host-specific tool grants or embedded `!` shell execution. This is an instruction-based skill, not an installed backend or an MCP server. No lammpkeeper MCP server is provided yet.

## Discovery and invocation

| Host | Project discovery | Invocation and notes |
| --- | --- | --- |
| Codex | `.agents/skills/lammpkeeper/`; Codex scans `.agents/skills` from the working directory up to the repository root and follows symlinked skill folders. | Use `/skills` to select the skill or mention `$lammpkeeper`. See [Codex skills](https://developers.openai.com/codex/skills). |
| Claude Code | `.claude/skills/lammpkeeper/`, linked to `../../.agents/skills/lammpkeeper`. Project skill folders may be symlink targets. | Invoke `/lammpkeeper`. If this is the first newly added skills directory, use `/reload-skills` when needed. These notes target local Claude Code terminal usage; they do not establish support for every cloud or Cowork environment. See [Claude Code skills](https://code.claude.com/docs/en/skills). |
| OpenCode V2 | `.agents/skills/lammpkeeper/` is supported alongside `.claude/skills/` and `.opencode/skills/`. `.agents` takes precedence over `.claude` for the same skill. | Mention `@lammpkeeper`, or let the agent load it through the `skill` tool. The ID is derived from the folder path: `lammpkeeper`. See [OpenCode V2 skills](https://opencode.ai/v2/docs/skills). |

Edit the canonical skill body and references once; hosts following the link see the same content. Do not maintain a second body in `.claude/skills`. If symlinks are unavailable, explicitly copy the **whole** `lammpkeeper` skill folder, including `references/`, and track synchronization drift whenever the canonical folder changes.

## Backend boundary

Discovery of this folder does not install Python dependencies or configure an environment. Once the selected environment contains the backend, the workflow executes `python -m lammpkeeper exec ...` or `python -m lammpkeeper run ...` using the canonical skill's command-selection instructions.

This integration requires no global installation or host configuration changes. The table distinguishes measured checks from documentation-only compatibility.

## Validation matrix

| Check | Status / evidence to record |
| --- | --- |
| Canonical folder and portable frontmatter | Canonical `.agents/skills/lammpkeeper` loaded successfully by this OpenCode session. |
| Claude relative symlink resolves to canonical folder | Measured: `../../.agents/skills/lammpkeeper` resolves to the canonical folder; body byte equality checked. |
| Codex discovers and explicitly loads skill | Not live-tested here; record host version and result when tested. |
| Local Claude Code discovers and explicitly loads skill | Not live-tested here; record host version, reload requirement, and result when tested. |
| OpenCode discovers and explicitly loads skill | Measured in this session: moving into the project advertised `lammpkeeper`; `skill({id: "lammpkeeper"})` returned the canonical `.agents` body. Installed host version was not captured; automatic triggering was not evaluated. |
| Backend `exec` / `run` runtime behavior | EXEC-1/2 verified on main `07983bd`; three paired AGENT-1 model runs additionally exercised the installed backend. See `docs/agent/AGENT-1.md` for outcomes and limitations. |

Host notes reflect the linked documentation consulted for this integration. Host versions, discovery behavior, and reload requirements can change; confirm them against the current documentation and the installed host. No live Claude Code or Codex testing is claimed.
