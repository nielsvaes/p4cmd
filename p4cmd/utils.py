import logging

def split_list_into_strings_of_length(input_list, max_length=100):
    """
    From incoming list of strings, build joined together strings that are clamped to a max size

    :param input_list:
    :param max_length: str clamp length
    """
    full_list_str = " ".join([str(arg) for arg in input_list])

    # if str is already below max length, just return it wrapped in a list
    if not len(full_list_str) > max_length:
        return [full_list_str]

    # Keep appending on the last string until we hit the max length
    # then add a new entry to the list and keep appending
    clamped_str_list = [""]
    for arg in input_list:
        current_str = clamped_str_list[-1]
        new_str = "{}{} ".format(current_str, arg)  # the space is deliberately placed, since the first item has no len

        # if new string is too long, just append the arg as a new item and skip to next arg
        if len(new_str) >= max_length:
            clamped_str_list.append("{} ".format(arg))  #
            continue

        # set latest to updated string
        clamped_str_list[-1] = new_str

    return clamped_str_list


def decode_dictionaries(info_dicts):
    """
    Decode list of dictionary keys and values into unicode from bytes
    """
    decoded_dicts = []
    for info_dict in info_dicts:
        decoded_dict = {k.decode(): v.decode() for k, v in info_dict.items()}
        decoded_dicts.append(decoded_dict)
    return decoded_dicts


def convert_to_list(value):
    """
    Converts a value to a list if it isn't already one.
    :param value: input value
    :return: list
    """
    if isinstance(value, tuple):
        converted = [v for v in value]
    else:
        converted = [value]
    return converted


def validate_not_empty(func):
    """
    Decorator to ensure file and folder lists are not empty before proceeding with Perforce operations
    """

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