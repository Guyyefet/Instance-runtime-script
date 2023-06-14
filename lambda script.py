import boto3
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2_resource = boto3.resource('ec2', 'us-east-1')
cloudwatch_client = boto3.client('cloudwatch')
sns_client = boto3.client('sns')

def lambda_handler(event, context):
    check_instance_tags()

def check_instance_tags():
    # Check tags of running instances and perform actions based on the tags.
    instances = ec2_resource.instances.filter(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])

    for instance in instances:
        is_protected = {'Key': 'Status', 'Value': 'Protected'} in instance.tags

        if is_protected:
            check_instance_runtime(instance)
            logger.info(f"Protected instance: {instance.id}")
        else:
            instance.stop()
            logger.info(f"Unprotected instance: {instance.id}")

def check_instance_runtime(instance):
    # Check the runtime of an instance and perform actions based on the runtime.
    instance_runtime = datetime.now(timezone.utc) - instance.launch_time
    instance_runtime_seconds = instance_runtime.total_seconds()
    cloudwatch_metric(instance, instance_runtime_seconds)

    if instance_runtime_seconds >= timedelta(weeks=1):
        logger.info(f'Instance has been running for more than 1 week, so it will be stopped: {instance.id}, Uptime: {instance_runtime_seconds} seconds')
        instance.stop()
    else:
        logger.info(f'Instance has been running for less than 1 week: {instance.id}, Uptime: {instance_runtime_seconds} seconds')

def cloudwatch_metric(instance, instance_runtime_seconds):
    # Send instance uptime metric data to CloudWatch. Creates the needed resources 
    # if they don't exist. 
    cloudwatch_client.put_metric_data(
        Namespace='Custom/Instance',
        MetricData=[
            {
                'MetricName': 'InstanceUptime',
                'Dimensions': [
                    {
                        'Name': 'InstanceId',
                        'Value': instance.id
                    },
                ],
                'Timestamp': datetime.now(timezone.utc),
                'Value': instance_runtime_seconds,
                'Unit': 'Seconds'
            }
        ]
    )

    alarm_name = f'instance_runtime_Alarm_{instance.id}'
    alarms = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])['MetricAlarms']

    if not alarms:
        create_alarm(instance, alarm_name)
        logger.info(f'Alarm created for instance: {instance.id}')
    else:
        logger.info(f'Alarm already exists for instance: {instance.id}')

def create_alarm(instance, alarm_name):
    # Creates an alarm for the metric and subscribe for a sns topic with the email
    # taken from the instance tag.
    cloudwatch_client.put_metric_alarm(
        AlarmName=alarm_name,
        AlarmActions=['arn:aws:sns:us-east-1:182021176759:instance_runtime_above_threshold'],
        MetricName='InstanceUptime',
        Namespace='Custom/Instance',
        Statistic='Average',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance.id}],
        Period=3600,
        EvaluationPeriods=1,
        Threshold=604800,
        ComparisonOperator='GreaterThanOrEqualToThreshold',
        TreatMissingData='notBreaching'
    )

    instance_email = get_instance_email(instance)

    sns_subscription = sns_client.subscribe(
        TopicArn='arn:aws:sns:us-east-1:182021176759:instance_runtime_above_threshold',
        Protocol='email',
        Endpoint=instance_email
    )

def get_instance_email(instance):
    return next((tag['Value'] for tag in instance.tags if tag['Key'] == 'Email'), None)
