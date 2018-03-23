from typing import List
from aztk.utils.command_builder import CommandBuilder
from aztk.utils import helpers
from aztk.utils import constants
from aztk import models as aztk_models
from aztk.spark.models import ClusterConfiguration
import azure.batch.models as batch_models

POOL_ADMIN_USER_IDENTITY = batch_models.UserIdentity(
    auto_user=batch_models.AutoUserSpecification(
        scope=batch_models.AutoUserScope.pool,
        elevation_level=batch_models.ElevationLevel.admin))

'''
Cluster create helper methods
'''
def __docker_run_cmd(docker_repo: str = None,
                     gpu_enabled: bool = False,
                     worker_on_master: bool = True,
                     file_mounts = None,
                     plugins = None,
                     mixed_mode = False) -> str:
    """
        Build the docker run command by setting up the environment variables
    """
    if gpu_enabled:
        cmd = CommandBuilder('nvidia-docker run')
    else:
        cmd = CommandBuilder('docker run')
    cmd.add_option('--net', 'host')
    cmd.add_option('--name', constants.DOCKER_SPARK_CONTAINER_NAME)
    cmd.add_option('-v', '/mnt/batch/tasks:/mnt/batch/tasks')

    if file_mounts:
        for mount in file_mounts:
            cmd.add_option('-v', '{0}:{0}'.format(mount.mount_path))

    cmd.add_option('-e', 'AZTK_WORKING_DIR=/mnt/batch/tasks/startup/wd')
    cmd.add_option('-e', 'AZ_BATCH_ACCOUNT_NAME=$AZ_BATCH_ACCOUNT_NAME')
    cmd.add_option('-e', 'BATCH_ACCOUNT_KEY=$BATCH_ACCOUNT_KEY')
    cmd.add_option('-e', 'BATCH_SERVICE_URL=$BATCH_SERVICE_URL')
    cmd.add_option('-e', 'STORAGE_ACCOUNT_NAME=$STORAGE_ACCOUNT_NAME')
    cmd.add_option('-e', 'STORAGE_ACCOUNT_KEY=$STORAGE_ACCOUNT_KEY')
    cmd.add_option('-e', 'STORAGE_ACCOUNT_SUFFIX=$STORAGE_ACCOUNT_SUFFIX')
    cmd.add_option('-e', 'SP_TENANT_ID=$SP_TENANT_ID')
    cmd.add_option('-e', 'SP_CLIENT_ID=$SP_CLIENT_ID')
    cmd.add_option('-e', 'SP_CREDENTIAL=$SP_CREDENTIAL')
    cmd.add_option('-e', 'SP_BATCH_RESOURCE_ID=$SP_BATCH_RESOURCE_ID')
    cmd.add_option('-e', 'SP_STORAGE_RESOURCE_ID=$SP_STORAGE_RESOURCE_ID')
    cmd.add_option('-e', 'AZ_BATCH_POOL_ID=$AZ_BATCH_POOL_ID')
    cmd.add_option('-e', 'AZ_BATCH_NODE_ID=$AZ_BATCH_NODE_ID')
    cmd.add_option('-e', 'AZTK_WORKER_ON_MASTER=$AZTK_WORKER_ON_MASTER')
    cmd.add_option('-e', 'AZTK_MIXED_MODE=$AZTK_MIXED_MODE')
    cmd.add_option(
        '-e', 'AZ_BATCH_NODE_IS_DEDICATED=$AZ_BATCH_NODE_IS_DEDICATED')
    cmd.add_option('-e', 'SPARK_WEB_UI_PORT=$SPARK_WEB_UI_PORT')
    cmd.add_option('-e', 'SPARK_WORKER_UI_PORT=$SPARK_WORKER_UI_PORT')
    cmd.add_option('-e', 'SPARK_CONTAINER_NAME=$SPARK_CONTAINER_NAME')
    cmd.add_option('-e', 'SPARK_SUBMIT_LOGS_FILE=$SPARK_SUBMIT_LOGS_FILE')
    cmd.add_option('-e', 'SPARK_JOB_UI_PORT=$SPARK_JOB_UI_PORT')

    # Environment computed on th node
    cmd.add_option('-e', 'AZTK_IS_MASTER=$AZTK_IS_MASTER')
    cmd.add_option('-e', 'AZTK_IS_WORKER=$AZTK_IS_WORKER')
    cmd.add_option('-e', 'AZTK_MASTER_IP=$AZTK_MASTER_IP')

    cmd.add_option('-p', '8080:8080')       # Spark Master UI
    cmd.add_option('-p', '7077:7077')       # Spark Master
    cmd.add_option('-p', '7337:7337')       # Spark Shuffle Service
    cmd.add_option('-p', '4040:4040')       # Job UI
    cmd.add_option('-p', '18080:18080')     # Spark History Server UI
    cmd.add_option('-p', '3022:3022')       # Docker SSH
    if plugins:
        for plugin in plugins:
            for port in plugin.ports:
                cmd.add_option('-p', '{0}:{1}'.format(port.internal, port.internal))       # Jupyter UI

    cmd.add_option('-d', docker_repo)
    cmd.add_argument('/bin/bash /mnt/batch/tasks/startup/wd/aztk/node_scripts/docker_main.sh')

    return cmd.to_str()

def _get_aztk_environment(worker_on_master, mixed_mode):
    envs = []
    envs.append(batch_models.EnvironmentSetting(name="AZTK_MIXED_MODE", value=mixed_mode))
    if worker_on_master is not None:
        envs.append(batch_models.EnvironmentSetting(
                name="AZTK_WORKER_ON_MASTER", value=worker_on_master))
    else:
        envs.append(batch_models.EnvironmentSetting(
                name="AZTK_WORKER_ON_MASTER", value=False))
    return envs

def __get_docker_credentials(spark_client):
    creds = []
    docker = spark_client.secrets_config.docker
    if docker:
        if docker.endpoint:
            creds.append(batch_models.EnvironmentSetting(
                name="DOCKER_ENDPOINT", value=docker.endpoint))
        if docker.username:
            creds.append(batch_models.EnvironmentSetting(
                name="DOCKER_USERNAME", value=docker.username))
        if docker.password:
            creds.append(batch_models.EnvironmentSetting(
                name="DOCKER_PASSWORD", value=docker.password))

    return creds


def __get_secrets_env(spark_client):
    shared_key = spark_client.secrets_config.shared_key
    service_principal = spark_client.secrets_config.service_principal
    if shared_key:
        return [
            batch_models.EnvironmentSetting(
                name="BATCH_SERVICE_URL", value=shared_key.batch_service_url),
            batch_models.EnvironmentSetting(
                name="BATCH_ACCOUNT_KEY", value=shared_key.batch_account_key),
            batch_models.EnvironmentSetting(
                name="STORAGE_ACCOUNT_NAME", value=shared_key.storage_account_name),
            batch_models.EnvironmentSetting(
                name="STORAGE_ACCOUNT_KEY", value=shared_key.storage_account_key),
            batch_models.EnvironmentSetting(
                name="STORAGE_ACCOUNT_SUFFIX", value=shared_key.storage_account_suffix),
        ]
    else:
        return [
            batch_models.EnvironmentSetting(
                name="SP_TENANT_ID", value=service_principal.tenant_id),
            batch_models.EnvironmentSetting(
                name="SP_CLIENT_ID", value=service_principal.client_id),
            batch_models.EnvironmentSetting(
                name="SP_CREDENTIAL", value=service_principal.credential),
            batch_models.EnvironmentSetting(
                name="SP_BATCH_RESOURCE_ID", value=service_principal.batch_account_resource_id),
            batch_models.EnvironmentSetting(
                name="SP_STORAGE_RESOURCE_ID", value=service_principal.storage_account_resource_id),
        ]


def __cluster_install_cmd(zip_resource_file: batch_models.ResourceFile,
                          gpu_enabled: bool,
                          docker_repo: str = None,
                          plugins = None,
                          worker_on_master: bool = True,
                          file_mounts = None,
                          mixed_mode: bool = False):
    """
        For Docker on ubuntu 16.04 - return the command line
        to be run on the start task of the pool to setup spark.
    """
    default_docker_repo = constants.DEFAULT_DOCKER_REPO if not gpu_enabled else constants.DEFAULT_DOCKER_REPO_GPU
    docker_repo = docker_repo or default_docker_repo

    shares = []

    if file_mounts:
        for mount in file_mounts:
            # Create the directory on the node
            shares.append('mkdir -p {0}'.format(mount.mount_path))

            # Mount the file share
            shares.append('mount -t cifs //{0}.file.core.windows.net/{2} {3} -o vers=3.0,username={0},password={1},dir_mode=0777,file_mode=0777,sec=ntlmssp'.format(
                mount.storage_account_name,
                mount.storage_account_key,
                mount.file_share_path,
                mount.mount_path
            ))

    setup = [
        'apt-get -y clean',
        'apt-get -y update',
        'apt-get install --fix-missing',
        'apt-get -y install unzip',
        'unzip $AZ_BATCH_TASK_WORKING_DIR/{0}'.format(
            zip_resource_file.file_path),
        'chmod 777 $AZ_BATCH_TASK_WORKING_DIR/aztk/node_scripts/setup_node.sh',
        '/bin/bash $AZ_BATCH_TASK_WORKING_DIR/aztk/node_scripts/setup_node.sh {0} {1} {2} "{3}"'.format(
            constants.DOCKER_SPARK_CONTAINER_NAME,
            gpu_enabled,
            docker_repo,
            __docker_run_cmd(docker_repo, gpu_enabled, worker_on_master, file_mounts, plugins, mixed_mode)),
    ]

    commands = shares + setup
    return commands

def generate_cluster_start_task(
        spark_client,
        zip_resource_file: batch_models.ResourceFile,
        gpu_enabled: bool,
        docker_repo: str = None,
        file_shares: List[aztk_models.FileShare] = None,
        plugins: List[aztk_models.PluginConfiguration] = None,
        mixed_mode: bool = False,
        worker_on_master: bool = True):
    """
        This will return the start task object for the pool to be created.
        :param cluster_id str: Id of the cluster(Used for uploading the resource files)
        :param zip_resource_file: Resource file object pointing to the zip file containing scripts to run on the node
    """

    resource_files = [zip_resource_file]
    spark_web_ui_port = constants.DOCKER_SPARK_WEB_UI_PORT
    spark_worker_ui_port = constants.DOCKER_SPARK_WORKER_UI_PORT
    spark_job_ui_port = constants.DOCKER_SPARK_JOB_UI_PORT

    spark_container_name = constants.DOCKER_SPARK_CONTAINER_NAME
    spark_submit_logs_file = constants.SPARK_SUBMIT_LOGS_FILE

    # TODO use certificate
    environment_settings = __get_secrets_env(spark_client) + [
        batch_models.EnvironmentSetting(
            name="SPARK_WEB_UI_PORT", value=spark_web_ui_port),
        batch_models.EnvironmentSetting(
            name="SPARK_WORKER_UI_PORT", value=spark_worker_ui_port),
        batch_models.EnvironmentSetting(
            name="SPARK_JOB_UI_PORT", value=spark_job_ui_port),
        batch_models.EnvironmentSetting(
            name="SPARK_CONTAINER_NAME", value=spark_container_name),
        batch_models.EnvironmentSetting(
            name="SPARK_SUBMIT_LOGS_FILE", value=spark_submit_logs_file),
    ] + __get_docker_credentials(spark_client) + _get_aztk_environment(worker_on_master, mixed_mode)

    # start task command
    command = __cluster_install_cmd(zip_resource_file, gpu_enabled, docker_repo, plugins, worker_on_master, file_shares, mixed_mode)

    return batch_models.StartTask(
        command_line=helpers.wrap_commands_in_shell(command),
        resource_files=resource_files,
        environment_settings=environment_settings,
        user_identity=POOL_ADMIN_USER_IDENTITY,
        wait_for_success=True)
