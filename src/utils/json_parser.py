import json
import re
from typing import Dict, List, Optional, Type, TypeVar, Union

from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel

from config import logger

# Generic type for Pydantic models
T = TypeVar("T", bound=BaseModel)


def clean_json_string(json_str: str) -> str:
    """Helper function to clean and prepare JSON string for parsing."""
    # Remove any BOM and special characters
    json_str = json_str.replace("\ufeff", "")

    # Remove comments
    json_str = re.sub(r"//.*?\n|/\*.*?\*/", "", json_str, flags=re.DOTALL)

    # Remove trailing commas
    json_str = re.sub(r",(\s*[\}\]])", r"\1", json_str)

    # Normalize newlines
    json_str = json_str.replace("\r\n", "\n").replace("\r", "\n")

    # Fix escaped quotes
    json_str = json_str.replace(r"\"", '"').replace(r"\'", "'")

    # Remove null bytes and other control characters except newlines and tabs
    json_str = "".join(char for char in json_str if char >= " " or char in "\n\t")

    return json_str.strip()


def wrap_list_if_needed(parsed_json: Union[Dict, List]) -> Dict:
    """Helper function to wrap lists in a dictionary if needed."""
    if isinstance(parsed_json, list):
        return {"data": parsed_json}
    return parsed_json


def ensure_json_object(json_str: str) -> str:
    """
    If the JSON string does not start with a { or [,
    assume it's missing its enclosing braces and wrap it with {}.
    """
    json_str = json_str.strip()
    if not (json_str.startswith("{") or json_str.startswith("[")):
        json_str = "{" + json_str.rstrip(",") + "}"
    return json_str


def extract_json_content(text: str, schema_model: Optional[Type[T]] = None) -> Optional[Dict]:
    """
    Extracts JSON content from text using multiple approaches:
    1. First tries using Langchain's JsonOutputParser.
    2. Falls back to a cleaned version using Langchain.
    3. Then searches for JSON delimited by triple backticks (even if extra text surrounds it).
    4. Finally, falls back to regex-based extraction if necessary.

    Supports schema validation with Pydantic and will wrap arrays in a 'data' field.
    """
    if not text or not isinstance(text, str):
        logger.error("Invalid input: text must be a non-empty string")
        return None

    json_parser = JsonOutputParser()

    # --- Attempt 1: Direct Langchain parsing ---
    try:
        result = json_parser.parse(text)
        if schema_model and result:
            result = schema_model(**result).dict()
        return wrap_list_if_needed(result)
    except Exception as langchain_error:
        logger.debug(f"Langchain parsing failed: {langchain_error}")

    # --- Attempt 2: Cleaned Langchain parsing ---
    try:
        cleaned_text = text.strip()

        # If text is within markdown code blocks, extract the inner content.
        if "```json" in cleaned_text:
            cleaned_text = cleaned_text.split("```json", 1)[-1].split("```", 1)[0].strip()
        elif "```" in cleaned_text:
            cleaned_text = cleaned_text.split("```", 1)[-1].split("```", 1)[0].strip()

        cleaned_text = cleaned_text.replace("`", "").strip()

        result = json_parser.parse(cleaned_text)
        if schema_model and result:
            result = schema_model(**result).dict()
        return wrap_list_if_needed(result)
    except Exception as cleaned_langchain_error:
        logger.debug(f"Cleaned Langchain parsing failed: {cleaned_langchain_error}")

    # --- Attempt 3: Extraction using triple backticks explicitly ---
    # This regex pattern will capture code fences with or without a language specifier.
    code_fence_pattern = r"```(?:\w+)?\s*([\s\S]*?)\s*```"
    matches = re.findall(code_fence_pattern, text, flags=re.DOTALL)
    if matches:
        for match_content in matches:
            try:
                json_str = clean_json_string(match_content)
                json_str = ensure_json_object(json_str)
                parsed_json = json.loads(json_str)
                result = wrap_list_if_needed(parsed_json)
                if schema_model and result:
                    result = schema_model(**result).dict()
                return result
            except Exception as e:
                logger.debug(f"Failed to parse JSON from code fence content: {e}")

    # --- Attempt 4: Fallback with generic regex patterns ---
    json_patterns = [
        r"(?s)\{.*?\}",  # Match {...}
        r"(?s)$begin:math:display$.*?$end:math:display$",  # Match [...]
    ]
    for pattern in json_patterns:
        for match in re.finditer(pattern, text):
            try:
                json_str = clean_json_string(match.group(0))
                json_str = ensure_json_object(json_str)
                parsed_json = json.loads(json_str)
                result = wrap_list_if_needed(parsed_json)
                if schema_model and result:
                    result = schema_model(**result).dict()
                return result
            except Exception as e:
                logger.debug(f"Failed to parse JSON with pattern {pattern}: {e}")
                continue

    logger.warning("All JSON extraction attempts failed")
    return None
