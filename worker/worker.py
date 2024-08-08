import logging.config
import os
import shutil
import time
import tempfile

import requests
import yaml
from pathlib import Path

from celery import Celery, task
from celery.contrib import rdb

import smtplib
from email.mime.text import MIMEText

TASK_TIMEOUT_SECONDS = int(os.environ.get("WORKER_TASK_TIMEOUT_SECONDS"))
RUN_COMMAND_TIMEOUT_SECONDS = int(os.environ.get("WORKER_SSH_TIMEOUT_SECONDS"))
COLLECTOR_ACCESS_TOKEN = os.environ.get("COLLECTOR_ACCESS_TOKEN")

TASK_SUBMIT_FAILURE_MESSAGE = os.environ.get("WORKER_TASK_SUBMIT_FAILURE_MESSAGE")
TASK_DEFAULT_FAILURE_MESSAGE = os.environ.get("WORKER_TASK_DEFAULT_FAILURE_MESSAGE")
COLLECTOR_HOST = os.environ.get("COLLECTOR_HOST")
COLLECTOR_PORT = os.environ.get("COLLECTOR_EXPOSE_PORT")
COLLECTOR = "{COLLECTOR_HOST}:{COLLECTOR_PORT}".format(COLLECTOR_HOST=COLLECTOR_HOST, COLLECTOR_PORT=COLLECTOR_PORT)

TRACK = os.environ.get('TRACK', 'main')
TASKS = ['prepare_data', 'score_cpu', 'score_gpu']

GET_STATUS_URL = 'http://{COLLECTOR}/get_status'.format(COLLECTOR=COLLECTOR)
GET_SCORES_URL = 'http://{COLLECTOR}/get_scores'.format(COLLECTOR=COLLECTOR)
REMOTE_RUN_COMMAND_URL = 'http://{COLLECTOR}/remote_run_command'.format(COLLECTOR=COLLECTOR)
SUBMIT_TASK_COMMAND = 'bash run_urgent_task.sh {track} {submission_id} "{submission_url}"'
FETCH_LOGS_COMMAND = 'bash fetch_logs_urgent_task.sh {track} {submission_id}'
CHECK_SLURM_COMMAND = "sacct -j {job_id} --format=State | sed '3p'"

app = Celery('worker')
app.config_from_object('celeryconfig')

logger = logging.getLogger()
logger.propagate = False


def _send_update(task_id, status, secret, virtual_host='/', extra=None):
    """
    Sends a status update about the running task.

    id: The task ID.
    status: The new status for the task. One of 'running', 'finished' or 'failed'.
    """
    task_args = {'status': status}
    if extra:
        task_args['extra'] = extra
    logger.info("Updating task=%s status to %s", task_id, status)
    with app.connection() as new_connection:
        # We need to send on the main virtual host, not whatever host we're currently
        # connected to.
        new_connection.virtual_host = virtual_host
        app.send_task(
            'apps.web.tasks.update_submission',
            args=(task_id, task_args, secret),
            connection=new_connection,
            queue="submission-updates",
        )


def put_blob(url, file_path):
    logger.info("Putting blob %s in %s" % (file_path, url))
    requests.put(
        url,
        data=open(file_path, 'rb'),
        headers={
            'x-ms-blob-type': 'BlockBlob',
            'x-ms-version': '2018-03-28',
        }
    )

@task(name="compute_worker_run")
def run_wrapper(task_id, task_args):
    try:
        run(task_id, task_args)
    except Exception as e:
        workspace = Path(tempfile.mkdtemp())
        stderr_url = task_args['stderr_url']
        submission_id = task_args['submission_id']
        Path(workspace / "stderr.txt").write_text(TASK_DEFAULT_FAILURE_MESSAGE)
        put_blob(stderr_url, (workspace / "stderr.txt").as_posix())
        _send_update(task_id, {'status': 'failed'}, task_args['secret'])
        send_failure_notification(submission_id, str(e))
        shutil.rmtree(workspace)

def get_scores(submission_id):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer {}".format(COLLECTOR_ACCESS_TOKEN)}
    data = { 'submission_id': submission_id, 'track': TRACK }
    response = requests.post(GET_SCORES_URL, headers=headers, json=data)
    return response.json()

def get_status(submission_id):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer {}".format(COLLECTOR_ACCESS_TOKEN)}
    data = { 'submission_id': submission_id, 'track': TRACK }
    response = requests.post(GET_STATUS_URL, headers=headers, json=data)
    return response.json()

# def put_task_args(submission_id, task_args):
#     headers = {"Content-Type": "application/json", "Authorization": "Bearer {}".format(COLLECTOR_ACCESS_TOKEN)}
#     data = { 'submission_id': submission_id, 'task_args': task_args, 'track': TRACK}
#     response = requests.post(PUT_TASK_ARGS_URL, headers=headers, json=data)
#     return response.text

def run(task_id, task_args):
    """
    Performs a Run.

    task_id: The tracking ID for this task.
    task_args: The input arguments for this task:
    """

    logger.info("Entering run task; task_id=%s, task_args=%s", task_id, task_args)
    output_url = task_args['output_url']
    stdout_url = task_args['stdout_url']
    stderr_url = task_args['stderr_url']
    secret = task_args['secret']

    start = time.time()

    _send_update(task_id, 'running', secret)

    workspace = Path(tempfile.mkdtemp())
    submission_id = task_args['submission_id']
    try:
        job_id = submit_task(task_args)
        logging.info("sent score task")
    except Exception as e:
        logging.error("Failed to submit task: %s", e)
        Path(workspace / "stderr.txt").write_text(TASK_SUBMIT_FAILURE_MESSAGE)
        put_blob(stderr_url, (workspace / "stderr.txt").as_posix())

        send_failure_notification(submission_id, TASK_SUBMIT_FAILURE_MESSAGE)
        _send_update(task_id, 'failed', secret)
        return

    running_tasks = TASKS[:]
    logging.info("waiting for task %s", running_tasks)
    failed = False

    cnt = 0
    while not failed:
        cnt += 1
        if cnt % 180 == 0:
            if job_has_failed(job_id):
                failed = True
                break

        if time.time() - start > TASK_TIMEOUT_SECONDS:
            failed = True
            break
        time.sleep(10)
        if len(running_tasks) == 0:
            break

        running_tasks_ = running_tasks[:]
        status = get_status(submission_id)
        for task in running_tasks_:
            task_status = status.get(task)
            if task_status == 'ok':
                running_tasks.remove(task)
                logging.info("waiting for task %s", running_tasks)
            elif task_status == 'error':
                failed = True
                break

    # Path(workspace / "stdout.txt").write_text(out)
    # put_blob(stdout_url, (workspace / "stdout.txt").as_posix())

    if failed:
        try:
            out, error = fetch_logs(submission_id)
        except:
            out = TASK_DEFAULT_FAILURE_MESSAGE

        Path(workspace / "stderr.txt").write_text(out)
        put_blob(stderr_url, (workspace / "stderr.txt").as_posix())

        send_failure_notification(submission_id, out)
        _send_update(task_id, 'failed', secret)
        return

    logging.info("collecting results")
    scores = get_scores(submission_id)

    score_text = ""
    for key, value in scores.items():
        score_text += "{}: {}\n".format(key, value)

    Path(workspace / "scores.txt").write_text(score_text)
    shutil.make_archive(workspace.as_posix(), 'zip', workspace.as_posix())
    put_blob(output_url, workspace.with_suffix('.zip').as_posix())

    _send_update(task_id, 'finished', secret)

def remote_run_command(ssh_command):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer {}".format(COLLECTOR_ACCESS_TOKEN)}
    data = { 'command': ssh_command }
    response = requests.post(REMOTE_RUN_COMMAND_URL, headers=headers, json=data, timeout=RUN_COMMAND_TIMEOUT_SECONDS)
    stdout, stderr = response.json()['stdout'], response.json()['stderr']
    return stdout, stderr

def submit_task(task_args):
    bundle_url = task_args['bundle_url']
    submission_id = task_args['submission_id']
    input_url = yaml.safe_load(requests.get(bundle_url).text)['input']
    submission_url = yaml.safe_load(requests.get(input_url).text)['res']
    ssh_command = SUBMIT_TASK_COMMAND.format(track=TRACK, submission_id=submission_id, submission_url=submission_url)
    stdout, stderr = remote_run_command(ssh_command)
    job_id = stdout.strip()
    return job_id

def fetch_logs(submission_id):
    ssh_command = FETCH_LOGS_COMMAND.format(track=TRACK, submission_id=submission_id)
    stdout, stderr = remote_run_command(ssh_command)
    return stdout, stderr

def job_has_failed(job_id):
    ssh_command = CHECK_SLURM_COMMAND.format(job_id=job_id)
    stdout, stderr = remote_run_command(ssh_command)
    for status in ["FAILED", "TIMEOUT", "CANCELLED", "STOPPED", "NODE_FAIL", "PREEMPTED", "OUT_OF_MEMORY"]:
        if status in stdout:
            return True
    return False

def send_failure_notification(submission_id, log):
    host = os.environ["WORKER_SMTP_HOST"]
    port = os.environ["WORKER_SMTP_PORT"]
    sender = os.environ["WORKER_EMAIL_SENDER"]
    password = os.environ["WORKER_EMAIL_SENDER_PASSWORD"]

    recipients = os.environ["WORKER_EMAIL_RECIPIENTS"]

    msg = MIMEText(log)
    msg["From"] = sender
    msg["To"] = recipients
    msg["Subject"] = "[urgent 2024] failed submission: {}, check the log".format(submission_id)

    with smtplib.SMTP_SSL(host, port) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
    logging.info("sent failure notification")
