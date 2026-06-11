"""
skills/ — composable agent capabilities.

Each skill is a small module exposing a NAME, a DESCRIPTION, and a
PROMPT fragment. The agent is a composable tool-calling loop from a set of skills, rather than doing one massive prompt with instructions. By adding skills we are not adding long prompt but a reusable capability. """

from . import eligibility, exchange, escalation

REGISTRY = [eligibility, exchange, escalation]


def assemble_skill_prompt():
    """Concatenate the prompt fragments of all registered skills."""
    blocks = []
    for skill in REGISTRY:
        blocks.append(f"## Skill: {skill.NAME}\n{skill.PROMPT.strip()}")
    return "\n\n".join(blocks)
