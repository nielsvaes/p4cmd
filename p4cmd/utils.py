import logging
import functools


def split_list_into_strings_of_length(input_list, max_length=100):
    """
    From incoming list of strings, build joined together strings that are clamped to a max size

    :param input_list:
    :param max_length: str clamp length
    """
    full_list_str = " ".join([str(arg) for arg in input_list])

    if len(full_list_str) <= max_length:
        return [full_list_str]

    clamped_str_list = [""]
    for arg in input_list:
        current_str = clamped_str_list[-1]
        new_str = f"{current_str}{arg} "

        if len(new_str) >= max_length:
            clamped_str_list.append(f"{arg} ")
            continue

        clamped_str_list[-1] = new_str

    return clamped_str_list


def decode_dictionaries(info_dicts):
    """Decode list of dictionary keys and values into unicode from bytes"""
    result = []
    for d in info_dicts:
        decoded = {}
        for k, v in d.items():
            dk = k.decode() if isinstance(k, bytes) else k
            dv = v.decode() if isinstance(v, bytes) else v
            decoded[dk] = dv
        result.append(decoded)
    return result


def convert_to_list(value):
    """
    Converts a value to a list if it isn't already one.
    :param value: input value
    :return: list
    """
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def validate_not_empty(func):
    """
    Decorator to ensure file and folder lists are not empty before proceeding with Perforce operations
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        file_or_folder_list = args[1] if len(args) > 1 else None

        if file_or_folder_list is not None and not isinstance(file_or_folder_list, list):
            file_or_folder_list = convert_to_list(file_or_folder_list)

        if not file_or_folder_list:
            logging.warning(f"Empty file list provided to {func.__name__}, operation skipped.")
            logging.warning(f"args: {args}")
            logging.warning(f"kwargs: {kwargs}")
            return []

        return func(*args, **kwargs)

    return wrapper
