import time

TASKS = {}


def create_task(task_id):
    if not task_id:
        return

    TASKS[task_id] = {
        "paused": False,
        "cancelled": False,
    }


def pause_task(task_id):
    if task_id in TASKS:
        TASKS[task_id]["paused"] = True


def resume_task(task_id):
    if task_id in TASKS:
        TASKS[task_id]["paused"] = False


def cancel_task(task_id):
    if task_id in TASKS:
        TASKS[task_id]["cancelled"] = True
        TASKS[task_id]["paused"] = False


def is_cancelled(task_id):
    return TASKS.get(task_id, {}).get("cancelled", False)


def wait_if_paused(task_id):
    while TASKS.get(task_id, {}).get("paused", False):
        if is_cancelled(task_id):
            return False

        time.sleep(1)

    return True


def remove_task(task_id):
    if not task_id:
        return

    TASKS.pop(task_id, None)