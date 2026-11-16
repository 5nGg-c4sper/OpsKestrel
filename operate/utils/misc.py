import json
import re


def convert_percent_to_decimal(percent):
    try:
        if percent is None:
            return None

        decimal_value = float(str(percent).strip().rstrip("%"))

        # Accept decimal fractions, percentages, and 0-1000 normalized values.
        if 0 <= decimal_value <= 1:
            return decimal_value
        if 1 < decimal_value <= 100:
            return decimal_value / 100
        if 100 < decimal_value <= 1000:
            return decimal_value / 1000

        raise ValueError(f"coordinate out of range: {percent}")
    except ValueError as e:
        print(f"[convert_percent_to_decimal] error: {e}")
        return None


def parse_operations(response):
    if response == "DONE":
        return {"type": "DONE", "data": None}
    elif response.startswith("CLICK"):
        # Adjust the regex to match the correct format
        click_data = re.search(r"CLICK \{ (.+) \}", response).group(1)
        click_data_json = json.loads(f"{{{click_data}}}")
        return {"type": "CLICK", "data": click_data_json}

    elif response.startswith("TYPE"):
        # Extract the text to type
        try:
            type_data = re.search(r"TYPE (.+)", response, re.DOTALL).group(1)
        except:
            type_data = re.search(r'TYPE "(.+)"', response, re.DOTALL).group(1)
        return {"type": "TYPE", "data": type_data}

    elif response.startswith("SEARCH"):
        # Extract the search query
        try:
            search_data = re.search(r'SEARCH "(.+)"', response).group(1)
        except:
            search_data = re.search(r"SEARCH (.+)", response).group(1)
        return {"type": "SEARCH", "data": search_data}

    return {"type": "UNKNOWN", "data": response}
