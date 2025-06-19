"""
Utility functions for handling prompts and formatting data for AI models.
"""

from typing import Any, Dict, List


def get_prompt(data: Dict[str, Any], wrapper_tag: str = "prompt", indent: int = 0, skip_empty: bool = True) -> str:
    """
    Converts a dictionary of key-value pairs into an XML-style prompt string.
    Handles nested dictionaries and lists at any level automatically.

    Args:
        data: Dictionary containing key-value pairs to convert
        wrapper_tag: The main tag to wrap all content in (default: 'prompt')
        indent: Number of spaces to indent the content (default: 0)
        skip_empty: Whether to skip empty/None values (default: True)

    Returns:
        A formatted string with XML-style tags

    Example:
        Input: {
            'date': '2024-03-21',
            'task': 'Research task',
            'posts': [1, 2, 3],
            'context': {
                'research': {
                    'findings': 'Some findings...',
                    'metadata': {
                        'source': 'Database A',
                        'confidence': 'High'
                    }
                },
                'analysis': 'details...'
            }
        }
        Output:
        <prompt>
            <date>
            2024-03-21
            </date>

            <task>
            Research task
            </task>

            <posts>
                <posts_item_1>
                1
                </posts_item_1>

                <posts_item_2>
                2
                </posts_item_2>

                <posts_item_3>
                3
                </posts_item_3>
            </posts>

            <context>
                <research>
                    <findings>
                    Some findings...
                    </findings>

                    <metadata>
                        <source>
                        Database A
                        </source>

                        <confidence>
                        High
                        </confidence>
                    </metadata>
                </research>

                <analysis>
                details...
                </analysis>
            </context>
        </prompt>
    """
    if not data:
        return ""

    # Filter out empty values if skip_empty is True
    if skip_empty:
        data = {k: v for k, v in data.items() if v is not None and (not isinstance(v, dict) or v)}

    if not data:  # If all values were empty
        return ""

    # Calculate indentation
    base_indent = " " * indent
    content_indent = " " * (indent + 4)

    # Build the string
    lines = [f"{base_indent}<{wrapper_tag}>"]

    for key, value in data.items():
        # Handle nested dictionaries
        if isinstance(value, dict):
            nested_xml = get_prompt(value, key, indent + 4, skip_empty)
            if nested_xml:  # Only add if there's content
                lines.append(nested_xml)
                lines.append("")  # Add blank line after nested content
        # Handle lists
        elif isinstance(value, (list, tuple)):
            if value:  # Only process non-empty lists
                lines.append(f"{content_indent}<{key}>")
                for i, item in enumerate(value, 1):
                    item_tag = f"{key}_item_{i}"
                    
                    # For dictionary items, recursively process their contents
                    if isinstance(item, dict):
                        lines.append(f"{' ' * (indent + 8)}<{item_tag}>")
                        
                        # Process each key-value pair in the dictionary item
                        for k, v in item.items():
                            inner_indent = ' ' * (indent + 12)
                            # Handle nested dictionary
                            if isinstance(v, dict):
                                nested_content = get_prompt({k: v}, k, indent + 12, skip_empty)
                                if nested_content:
                                    lines.append(nested_content)
                            # Handle nested list
                            elif isinstance(v, (list, tuple)):
                                nested_content = get_prompt({k: v}, k, indent + 12, skip_empty)
                                if nested_content:
                                    lines.append(nested_content)
                            # Handle simple value
                            else:
                                str_value = str(v).strip()
                                if str_value:
                                    lines.append(f"{inner_indent}<{k}>")
                                    for val_line in str_value.split("\n"):
                                        lines.append(f"{inner_indent}{val_line}")
                                    lines.append(f"{inner_indent}</{k}>")
                        
                        lines.append(f"{' ' * (indent + 8)}</{item_tag}>")
                    else:
                        # Handle primitive types
                        lines.append(f"{' ' * (indent + 8)}<{item_tag}>")
                        # Convert item to string and handle multi-line values
                        item_str = str(item).strip()
                        item_lines = item_str.split("\n")
                        lines.extend(f"{' ' * (indent + 8)}{line}" for line in item_lines)
                        lines.append(f"{' ' * (indent + 8)}</{item_tag}>")
                    
                    lines.append("")  # Add blank line between list items
                
                # Remove the last blank line if it exists
                if lines and not lines[-1]:
                    lines.pop()
                
                lines.append(f"{content_indent}</{key}>")
                lines.append("")  # Add blank line after list
        else:
            # Convert value to string and handle multi-line values
            value_str = str(value).strip()
            if value_str:
                lines.append(f"{content_indent}<{key}>")
                # Indent each line of the value
                value_lines = value_str.split("\n")
                lines.extend(f"{content_indent}{line}" for line in value_lines)
                lines.append(f"{content_indent}</{key}>")
                lines.append("")  # Add blank line between entries

    # Remove the last blank line if it exists
    if lines and not lines[-1]:
        lines.pop()

    lines.append(f"{base_indent}</{wrapper_tag}>")

    return "\n".join(lines)


# We can remove format_prompt_context since dict_to_xml_string now handles nested structures
