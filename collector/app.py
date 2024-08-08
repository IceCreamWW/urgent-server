from flask import Flask, request
import paramiko
import json
import os
from filelock import FileLock
from pathlib import Path

app = Flask(__name__)

DATA = Path("data/")
TOKEN = os.environ["COLLECTOR_ACCESS_TOKEN"]
SSH_MAX_RETRIES = int(os.environ["COMPUTE_NODE_SSH_MAX_RETRIES"])

def update_json(filepath, data_new):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(filepath.with_suffix('.lock')):
        data = json.loads(filepath.read_text()) if filepath.exists() else {}
        data.update(data_new)
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))

@app.route('/put_status', methods=['POST'])
def put_status():
    if request.headers.get('Authorization') != 'Bearer ' + TOKEN:
        return 'Unauthorized', 401
    status_file = DATA / str(request.json['track']) / str(request.json['submission_id']) / 'status.json'
    update_json(status_file, request.json['status'])
    return 'OK'

@app.route('/put_scores', methods=['POST'])
def put_scores():
    if request.headers.get('Authorization') != 'Bearer ' + TOKEN:
        return 'Unauthorized', 401
    scores_file = DATA / str(request.json['track']) / str(request.json['submission_id']) / 'scores.json'
    update_json(scores_file, request.json['scores'])
    return 'OK'

@app.route('/put_task_args', methods=['POST'])
def put_task_args():
    if request.headers.get('Authorization') != 'Bearer ' + TOKEN:
        return 'Unauthorized', 401
    task_args_file = DATA / str(request.json['track']) / str(request.json['submission_id']) / 'task_args.json'
    update_json(task_args_file, request.json['task_args'])
    return 'OK'

@app.route('/get_scores', methods=['POST'])
def get_scores():
    if request.headers.get('Authorization') != 'Bearer ' + TOKEN:
        return 'Unauthorized', 401

    scores_file = DATA / str(request.json['track']) / str(request.json['submission_id']) / 'scores.json'
    with FileLock(scores_file.with_suffix('.lock')):
        return scores_file.read_text() if scores_file.exists() else '{}'

@app.route('/get_status', methods=['POST'])
def get_status():
    if request.headers.get('Authorization') != 'Bearer ' + TOKEN:
        return 'Unauthorized', 401

    status_file = DATA / str(request.json['track']) / str(request.json['submission_id']) / 'status.json'
    with FileLock(status_file.with_suffix('.lock')):
        return status_file.read_text() if status_file.exists() else '{}'

@app.route('/remote_run_command', methods=['POST'])
def remote_run_command():
    if request.headers.get('Authorization') != 'Bearer ' + TOKEN:
        return 'Unauthorized', 401
    command = request.json['command']
    with FileLock(DATA / 'remote_run_command.lock'):
        stdin, stdout, stderr = ssh_run_command(command)
    stdout = stdout.read().decode()
    stderr = stderr.read().decode()
    return {'stdout': stdout, 'stderr': stderr}

def ssh_connect():
    SSH_LOGIN_ARGS = {
        'hostname': os.environ["COMPUTE_NODE_SSH_HOSTNAME"],
        'port': os.environ["COMPUTE_NODE_SSH_PORT"],
        'username': os.environ["COMPUTE_NODE_SSH_USERNAME"],
        'password': os.environ["COMPUTE_NODE_SSH_PASSWORD"],
    }
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for _ in range(SSH_MAX_RETRIES):
        try:
            client.connect(**SSH_LOGIN_ARGS)
            break
        except:
            logging.error("SSH authentication failed.")
            time.sleep(10)
            continue
    return client

def ssh_run_command(command):
    global ssh_client
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command)
        return stdin, stdout, stderr
    except:
        logging.error("SSH command failed. Retry...")
        ssh_client = ssh_connect()
        stdin, stdout, stderr = ssh_client.exec_command(command)
        return stdin, stdout, stderr


if __name__ == '__main__':
    global ssh_client
    ssh_client = ssh_connect()
    app.run(host='0.0.0.0', port=80)
