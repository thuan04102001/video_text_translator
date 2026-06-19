import os
import re


def video_exists_in_folder(folder, profile_id, video_id):

    if not os.path.exists(folder):
        return False

    files = os.listdir(folder)

    target = f"-{profile_id}-{video_id}"

    for file in files:

        name_without_ext = os.path.splitext(file)[0]

        if name_without_ext.endswith(target):
            return True

    return False