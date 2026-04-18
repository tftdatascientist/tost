### Sytuacje powodujące nie naturalny wzrost zużytych tokenów 

Cache invalidation bug: W agentach/workflowach cache nie odczytuje się poprawnie, kontekst (200k tokenów) naliczany jako nowy przy każdym kroku – limit Max wyczerpuje się w 19 min zamiast 5h.

Auto Compact + zmienne prompty: Kompresja kontekstu zapomina instrukcje z CLAUDE.md, wymuszając pełne Write.

Za dużo MCP/skills/plugins: Maniakalne używanie modułów (Midnight Coding Prompts) – 200k+ tokenów na sesję.

Długie sesje bez resetu: Liniowy wzrost do overflow okna (200k Opus 4.6), potem kompresja generuje extra tokeny.

Think mode na wszystkim: Filozofowanie Claude marnuje output tokeny (5x droższe).