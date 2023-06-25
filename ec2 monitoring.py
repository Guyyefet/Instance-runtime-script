import boto3
import botocore.exceptions
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EC2_RESOURCE = boto3.resource('ec2', 'us-east-1')
CLOUDWATCH_CLIENT = boto3.client('cloudwatch')
SNS_CLIENT = boto3.client('sns')


class ProtectedEC2Instance:
    def __init__(self, protectedEC2Instance):
        self.protectedEC2Instance = protectedEC2Instance
        self.id = protectedEC2Instance.id
        self.alarms = [
        {
            'name': f"one_week_uptime_alarm {self.id}",
            'actions': ['arn:aws:sns:us-east-1:182021176759:instance_one_week_alarm'],
            'threshold': 3600
        },
        {
            'name': f"two_weeks_uptime_alarm {self.id}",
            'actions': [
                'arn:aws:sns:us-east-1:182021176759:instance_two_weeks_alarm',
                "arn:aws:swf:us-east-1:182021176759:action/actions/AWS_EC2.InstanceId.Stop/1.0"
                       ],
            'threshold': 7200
        }
    ]
        self.sns_topics = [
        {'TopicArn': 'arn:aws:sns:us-east-1:182021176759:instance_one_week_alarm'},
        {'TopicArn': 'arn:aws:sns:us-east-1:182021176759:instance_two_weeks_alarm'},
    ]

    def calculate_instance_uptime(self):
        instance_uptime = datetime.now(timezone.utc) - self.protectedEC2Instance.launch_time
        instance_uptime = int(instance_uptime.total_seconds())
        return instance_uptime

    def get_email(self):
        try:
            email = next((tag['Value'] for tag in self.protectedEC2Instance.tags if tag['Key'] == 'Email'))
        except(KeyError, StopIteration) as e:
            logger.error(f"{self.id} has no 'Email' tag: {str(e)}")
            return None
        else:
            return email

        # email = next((tag['Value'] for tag in self.protectedEC2Instance.tags if tag['Key'] == 'Email'), None)
        # if email is not None:
        #     return email
        # else:
        #     logger.warning(f"{self.protectedEC2Instance.id} has no 'Email' tag")

    def create_monitoring(self):
        # Sends instance uptime metric data to CloudWatch and creates the necessary resources if they don't exist.
        try:
            CLOUDWATCH_CLIENT.put_metric_data(
            Namespace='Custom/Instance',
            MetricData=[
                {
                    'MetricName': 'InstanceUptime',
                    'Dimensions': [
                        {
                            'Name': 'InstanceId',
                            'Value': self.id
                        },
                    ],
                    'Timestamp': datetime.now(timezone.utc),
                    'Value': self.calculate_instance_uptime(),
                    'Unit': 'Seconds'
                }
            ]
        )
    
            alarm_names = [alarm['name'] for alarm in self.alarms]
            existing_alarms = CLOUDWATCH_CLIENT.describe_alarms(AlarmNames=alarm_names)['MetricAlarms']
            if not existing_alarms:
                for alarm in self.alarms:
                    CLOUDWATCH_CLIENT.put_metric_alarm(
                    AlarmName=alarm["name"],
                    AlarmActions=alarm["actions"],
                    MetricName='InstanceUptime',
                    Namespace='Custom/Instance',
                    Statistic='Average',
                    Dimensions=[{'Name': 'InstanceId', 'Value': self.id}],
                    Period=3600,
                    EvaluationPeriods=1,
                    Threshold=alarm["threshold"],
                    ComparisonOperator='GreaterThanOrEqualToThreshold',
                    TreatMissingData='notBreaching'
                )

                logger.info(f'Alarm been created for instance: {self.id}')
            else:
                logger.info(f'Alarm already exists for instance: {self.id}')

            for sns_topic in self.sns_topics:
              sns_subscription = SNS_CLIENT.subscribe(
              TopicArn=sns_topic['TopicArn'],
              Protocol='email',
              Endpoint=self.get_email()
            )
            
        except botocore.exceptions.ClientError as e:
            logger.error(f'Error occurred while creating monitoring: {str(e)}')
        except botocore.exceptions.ParamValidationError as e:
            logger.error(f'Invalid parameters for monitoring: {str(e)}')
        except Exception as e:
            logger.error(f'An unexpected error occurred: {str(e)}')

def lambda_handler(event, context):
    get_relevant_instances()

def get_relevant_instances():
    # filters the relevant instances and checks for the protected tag.
    # in case it protected ,creates its monitoring resources based on the ProtectedEC2Instance class. 
    # Stops unprotected instances.
    instances = EC2_RESOURCE.instances.filter(Filters=[
        {'Name': 'instance-state-name', 'Values': ['running']},
        {'Name': 'tag:Environment', 'Values': ['Development']}
        ]
    )

    protected_instances = []
    unprotected_instances= []
    for instance in instances:
        is_protected = {'Key': 'Status', 'Value': 'Protected'} in instance.tags

        if is_protected:
            protected_instances.append(instance.id)
            protected_instance = ProtectedEC2Instance(instance)
            protected_instance.create_monitoring()
        else:
            unprotected_instances.append(instance.id)
            instance.stop()

    logger.info(f"Protected instances: {protected_instances}")
    logger.info(f"Stopped instances: {unprotected_instances}")


