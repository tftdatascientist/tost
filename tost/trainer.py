"""Context Engineering Trainer — curriculum and Haiku API integration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Lesson:
    """Single lesson within a module."""
    title: str
    objective: str
    prompt_hint: str  # injected into Haiku system prompt for this lesson


@dataclass
class Module:
    """Training module covering one environment."""
    id: str
    name: str
    icon: str
    description: str
    lessons: list[Lesson]


CURRICULUM: list[Module] = [
    Module(
        id="claude_code",
        name="Claude Code",
        icon="CC",
        description="CLAUDE.md, hooks, MCP servers, context window management",
        lessons=[
            Lesson(
                title="CLAUDE.md — your persistent instructions",
                objective="Understand how CLAUDE.md shapes every conversation",
                prompt_hint=(
                    "Teach the user about CLAUDE.md files: global (~/.claude/CLAUDE.md) vs project-level, "
                    "how they inject persistent instructions into every session, priority order, and best "
                    "practices for keeping them concise. Give a practical example of a good CLAUDE.md entry. "
                    "Ask the user to describe what they'd put in their own CLAUDE.md."
                ),
            ),
            Lesson(
                title="Hooks — automated context injection",
                objective="Learn how hooks inject context at session start and tool calls",
                prompt_hint=(
                    "Explain Claude Code hooks: PreToolUse, PostToolUse, session start hooks in settings.json. "
                    "Show how hooks can inject context automatically (e.g., linting results, git status). "
                    "Discuss the difference between hooks and MCP. Ask the user to design a hook for their workflow."
                ),
            ),
            Lesson(
                title="MCP servers — extending the context reach",
                objective="Understand MCP as a bridge between Claude and external data",
                prompt_hint=(
                    "Explain MCP (Model Context Protocol) servers: what they are, how they expose tools and "
                    "resources to Claude Code. Cover practical examples: Notion MCP, filesystem MCP, database MCP. "
                    "Discuss when to use MCP vs hooks vs manual context. Ask the user which MCP servers "
                    "would benefit their stack."
                ),
            ),
            Lesson(
                title="Context window economy",
                objective="Manage token budget — what to include, what to defer",
                prompt_hint=(
                    "Teach token-aware context engineering: how the context window fills up (system prompt, "
                    "tools, conversation history, injected files), cache mechanics (read vs creation), "
                    "strategies to minimize overhead (slim CLAUDE.md, fewer plugins, targeted file reads). "
                    "Reference TOST's cost simulator as a tool to measure this. Quiz the user on trade-offs."
                ),
            ),
        ],
    ),
    Module(
        id="vscode_terminal",
        name="VS Code Terminal",
        icon="VS",
        description="IDE integration, terminal workflows, extension context",
        lessons=[
            Lesson(
                title="Terminal as context source",
                objective="Use terminal output as structured context for Claude",
                prompt_hint=(
                    "Explain how VS Code terminal output feeds into Claude Code sessions: command results, "
                    "error messages, test output. Cover the '!' prefix for running commands in-session. "
                    "Discuss strategies for keeping terminal context relevant (piping, filtering). "
                    "Ask the user about their typical terminal-to-Claude workflow."
                ),
            ),
            Lesson(
                title="Workspace settings as context layer",
                objective="Configure VS Code to enhance Claude's understanding",
                prompt_hint=(
                    "Cover .vscode/settings.json, tasks.json, launch.json as implicit context. "
                    "Explain how project-level CLAUDE.md in the workspace root gives Claude project awareness. "
                    "Discuss multi-root workspaces and how context scope changes. "
                    "Ask the user to identify which workspace settings would help Claude in their project."
                ),
            ),
        ],
    ),
    Module(
        id="notion",
        name="Notion",
        icon="NT",
        description="Knowledge base, structured data, MCP connector",
        lessons=[
            Lesson(
                title="Notion as structured knowledge base",
                objective="Design Notion databases that Claude can query effectively",
                prompt_hint=(
                    "Teach how to structure Notion for AI consumption: databases with typed properties, "
                    "consistent page templates, tagging systems. Explain that the Notion MCP server "
                    "lets Claude search, read, and create pages. Cover what makes a Notion structure "
                    "'context-friendly' vs human-only-friendly. Ask the user to describe their current "
                    "Notion setup and suggest improvements."
                ),
            ),
            Lesson(
                title="Notion MCP — live context bridge",
                objective="Connect Notion as a real-time context source via MCP",
                prompt_hint=(
                    "Walk through the Notion MCP setup: authentication, available tools (search, fetch, "
                    "create, update). Discuss practical patterns: storing project specs in Notion and "
                    "having Claude pull them mid-conversation, writing meeting notes that Claude can reference. "
                    "Cover rate limits and token costs of fetching large pages. "
                    "Ask the user to design a Notion→Claude context pipeline for their use case."
                ),
            ),
        ],
    ),
    Module(
        id="obsidian",
        name="Obsidian",
        icon="OB",
        description="Vault as context source, linking, templates, local-first",
        lessons=[
            Lesson(
                title="Vault structure for AI context",
                objective="Design an Obsidian vault that serves as a context repository",
                prompt_hint=(
                    "Explain how Obsidian's local-first markdown vault is ideal for context engineering: "
                    "files are on disk so Claude Code can read them directly. Cover folder structure strategies "
                    "(PARA, Zettelkasten), frontmatter/YAML as structured metadata, MOCs (Maps of Content) "
                    "as context entry points. Ask the user about their vault structure and suggest "
                    "context-optimization tweaks."
                ),
            ),
            Lesson(
                title="Templates and metadata for context injection",
                objective="Use Obsidian templates to create AI-ready documents",
                prompt_hint=(
                    "Cover Obsidian templates with YAML frontmatter that Claude can parse: status fields, "
                    "tags, related-notes links. Explain Dataview queries as a way to build dynamic context. "
                    "Discuss the pattern: write in Obsidian → Claude reads vault files → outputs back to vault. "
                    "Ask the user to create a template schema for their project notes."
                ),
            ),
        ],
    ),
    Module(
        id="n8n",
        name="n8n",
        icon="N8",
        description="Automation workflows, API pipelines, context orchestration",
        lessons=[
            Lesson(
                title="n8n as context orchestrator",
                objective="Build workflows that prepare and deliver context to Claude",
                prompt_hint=(
                    "Explain n8n's role in context engineering: automated workflows that gather data from "
                    "multiple sources (APIs, databases, files) and package it for Claude consumption. "
                    "Cover webhook triggers, HTTP request nodes, and the AI Agent node. "
                    "Discuss patterns: scheduled context refresh, event-driven context injection. "
                    "Ask the user what data sources they'd want to automate into their context pipeline."
                ),
            ),
            Lesson(
                title="AI Agent node — Claude in n8n workflows",
                objective="Use n8n's AI Agent node to chain Claude calls with context",
                prompt_hint=(
                    "Walk through the n8n AI Agent node: connecting Anthropic API, tool use, memory. "
                    "Explain multi-step workflows: fetch context → call Claude → store output → trigger next step. "
                    "Cover token budget management in automated pipelines (you pay per run!). "
                    "Ask the user to sketch a workflow that combines at least 2 data sources into a Claude call."
                ),
            ),
        ],
    ),
    Module(
        id="flowise",
        name="Flowise",
        icon="FL",
        description="Visual LLM chains, RAG pipelines, context injection nodes",
        lessons=[
            Lesson(
                title="Flowise chains for context engineering",
                objective="Build visual context pipelines with Flowise",
                prompt_hint=(
                    "Explain Flowise as a visual chain builder for LLM applications: drag-and-drop nodes, "
                    "document loaders, vector stores, prompt templates. Cover how Flowise differs from direct "
                    "API calls — it manages the context assembly visually. Discuss RAG patterns: "
                    "embed documents → retrieve relevant chunks → inject into prompt. "
                    "Ask the user what kind of documents they'd want to RAG-enable."
                ),
            ),
            Lesson(
                title="RAG pipelines — retrieval-augmented context",
                objective="Design a RAG pipeline that delivers relevant context on demand",
                prompt_hint=(
                    "Deep dive into RAG with Flowise: choosing embedding models, chunking strategies "
                    "(size, overlap), vector store selection (Pinecone, Chroma, local). "
                    "Explain the trade-off: more chunks = more context = more tokens = higher cost. "
                    "Cover reranking and filtering to keep context lean. "
                    "Ask the user to design chunk parameters for their specific document types."
                ),
            ),
        ],
    ),
    Module(
        id="typebot",
        name="Typebot",
        icon="TB",
        description="Conversational flows, context passing, user-facing interfaces",
        lessons=[
            Lesson(
                title="Typebot as context collection interface",
                objective="Use conversational flows to gather structured context from users",
                prompt_hint=(
                    "Explain Typebot's role: building conversational interfaces that collect structured "
                    "user input before passing it to Claude. Cover flow design: conditional logic, "
                    "variable capture, input validation. Discuss how Typebot output can feed into "
                    "n8n workflows or direct API calls. "
                    "Ask the user what information they'd want to collect from end users before an AI call."
                ),
            ),
            Lesson(
                title="End-to-end: Typebot → n8n → Claude → response",
                objective="Wire a complete context pipeline from user input to AI response",
                prompt_hint=(
                    "Walk through a full pipeline: Typebot collects user intent and parameters → "
                    "webhook triggers n8n → n8n enriches context from Notion/Obsidian/DB → "
                    "n8n calls Claude with assembled context → response flows back to Typebot. "
                    "Discuss latency, token costs, and error handling at each stage. "
                    "Ask the user to map their own end-to-end pipeline using these tools."
                ),
            ),
        ],
    ),
]


SYSTEM_PROMPT_BASE = """\
You are a Context Engineering Trainer — an expert instructor teaching \
practical context engineering for AI-powered development workflows.

Your student is learning how to optimize the context they provide to Claude \
across multiple tools: Claude Code, VS Code Terminal, Notion, Obsidian, n8n, \
Flowise, and Typebot.

Style rules:
- Be concise but thorough. Use bullet points and examples.
- After explaining a concept, ALWAYS ask the student a question or give them \
a mini-exercise to check understanding.
- Use real-world examples relevant to software development and AI automation.
- When the student answers, give constructive feedback and move forward.
- If the student says "next" or "skip", move to the key takeaway and wrap up.
- Keep responses under 300 words.
- Respond in Polish.

Current module: {module_name}
Current lesson: {lesson_title}
Objective: {lesson_objective}

Lesson-specific instructions:
{prompt_hint}
"""


@dataclass
class ChatMessage:
    role: str  # "user" or "assistant"
    content: str


@dataclass
class TrainerState:
    """Tracks progress through the curriculum."""
    current_module: int = 0
    current_lesson: int = 0
    history: list[ChatMessage] = field(default_factory=list)
    completed_modules: set[str] = field(default_factory=set)

    @property
    def module(self) -> Module:
        return CURRICULUM[self.current_module]

    @property
    def lesson(self) -> Lesson:
        return self.module.lessons[self.current_lesson]

    def advance(self) -> bool:
        """Move to next lesson/module. Returns False if curriculum is done."""
        self.history.clear()
        if self.current_lesson + 1 < len(self.module.lessons):
            self.current_lesson += 1
            return True
        self.completed_modules.add(self.module.id)
        if self.current_module + 1 < len(CURRICULUM):
            self.current_module += 1
            self.current_lesson = 0
            return True
        return False

    def jump_to_module(self, index: int) -> None:
        """Jump to a specific module."""
        self.current_module = max(0, min(index, len(CURRICULUM) - 1))
        self.current_lesson = 0
        self.history.clear()

    def build_system_prompt(self) -> str:
        mod = self.module
        les = self.lesson
        return SYSTEM_PROMPT_BASE.format(
            module_name=mod.name,
            lesson_title=les.title,
            lesson_objective=les.objective,
            prompt_hint=les.prompt_hint,
        )

    def build_messages(self) -> list[dict]:
        """Build messages list for Anthropic API."""
        msgs = []
        for m in self.history:
            msgs.append({"role": m.role, "content": m.content})
        return msgs


def call_haiku(state: TrainerState, user_input: str | None = None) -> str:
    """Send a message to Haiku and get a response."""
    import anthropic

    if user_input:
        state.history.append(ChatMessage(role="user", content=user_input))
    elif not state.history:
        # First message — ask Haiku to introduce the lesson
        state.history.append(ChatMessage(
            role="user",
            content="Start this lesson. Introduce the topic and begin teaching.",
        ))

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=state.build_system_prompt(),
        messages=state.build_messages(),
    )

    assistant_text = response.content[0].text
    state.history.append(ChatMessage(role="assistant", content=assistant_text))
    return assistant_text
