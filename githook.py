from flask import Flask, request, abort
import json
import logging
import threading
import Queue
import requests
from time import time
from datetime import datetime
from subprocess import *
import sys
import re

logging.basicConfig(filename='/skywatch/logs/githook1.log', format='[%(asctime)s, %(levelname)s] %(message)s', level=logging.DEBUG)

app = Flask(__name__)
queue = Queue.Queue() # Yes, globals are bad. I'm just trying to get this done

project_channel_map = {
    'front-end/website': 'website',
    'front-end/quasar': 'quasar',
    'front-end/admin-panel-front-end': 'quasar',
    'api/api': 'quasar',
    'supernova/front-end': 'supernova',
    'supernova/api': 'supernova',
    'front-end/remotex': 'front-end/remotex',
    'front-end/remotex-admin': 'front-end/remotex',
    'front-end/maxq': 'front-end/maxq'
}

# Custom exception type for signalling nonzero exit code from a Popen call
class SubprocessError(Exception):
    pass

#accept post requests to base url
@app.route('/', methods=['POST'])
def accept_request():
    global queue
    ip = request.remote_addr
    logging.info('Request recieved at ' + datetime.fromtimestamp(time()).strftime('%Y-%m-%d %H:%M:%S'))
    logging.info('remote address: ' + ip)
    if (ip != '107.178.218.39'):  
        logging.warning('Foreign IP address, program exited')
        abort(403)
    else:
        logging.info('IP address check passed, continuing program')
        queue.put(request.data.decode('utf8'))

    return 'ok'

def after_request(q):
    # By default, raises a SubprocessError (custom exception, above) for non-zero exit statuses. Pass critical=False to log warning and continue instead.
    def popen_cmd(cmd, shell=False, cwd=None, critical=True):
        process = Popen(cmd, stdout=PIPE, shell=shell, cwd=cwd, stderr=STDOUT, universal_newlines=True)
        output = process.communicate()[0]
        if output: logging.info(output)
        if process.returncode != 0:
            if type(cmd) != str:
                cmd = ' '.join(cmd)
            if critical:
                raise SubprocessError('Command "%s" exited with code %s' % (cmd, process.returncode))
            else:
                logging.warning('Command "%s" exited with code %s' % (cmd, process.returncode))
        return process.returncode
    def slack_post(project, msg): # If project isn't in the map, channel = project. Allows sending by project name or channel name
        channel = project_channel_map.get(project, project)
        slack_url = 'https://hooks.slack.com/services/T02KGSHG7/'
        if channel == 'development':
            slack_url += 'B0F9MR9TQ/SY73BeIR2aOLxmYkBFYt9jWh'
        elif channel == 'website':
            slack_url += 'B0FGN483E/zjSoxDF8W9lwfy1HydggTqac'
        elif channel == 'quasar':
            slack_url += 'B0FGR1HFV/DQJYDrrnQfRb1FuThFvOEE15'
        elif channel == 'supernova':
            slack_url += 'B0FGPQFAR/DHAUcKrS14x81xCOwdxhK2Ye'
	elif channel == 'front-end/remotex':
	    slack_url += 'B0M2CSG91/7YQJbHnGkUrapFY15zBMJyAs'
        elif channel == 'front-end/maxq':
	    slack_url += 'B141BH36V/80y62YmsvXuba8xTHEZFJ68s'
	else:
            logging.warning('Skipping unrecognized channel name "%s"', channel)
            return
        data = {
            'username': 'Build Agent',
            'text': msg,
            'icon_emoji': ':hourglass:'
        }
        requests.post(slack_url, data=json.dumps(data))
    def start_msg(project, branch, version, deploy=False):
        return 'Started build%s of %s %s, image version %s' % (' and deploy' if deploy else '', project, branch, version)
    def end_msg(project, branch, version, deploy=False):
        return 'Finished build%s of %s %s, image version %s' % (' and deploy' if deploy else '', project, branch, version)
    def start(branch='master'):
	return 'Starting npm install and grunt build for %s' % branch
    def finish(branch='master'):
	return 'Finished npm install and grunt build for %s' % branch

    def build_quasar_fe(project, branch, end_msg=True):
        stage = 'prod' if branch == 'master' else branch
        popen_cmd('git reset --hard HEAD && git fetch -p && git checkout %s && git pull' % branch, shell=True, cwd='/skywatch/repos/quasar-frontend')
        with open('/skywatch/repos/quasar-frontend/package.json', 'r') as f:
            package_json = json.load(f)
            version_str = str(package_json['version'])
        with open('/skywatch/quasar_fe_version.json', 'r') as f:
            version_json = json.load(f)
            if version_json[stage]['last_version'] != version_str:
                version_json[stage]['build'] = 0
                version_json[stage]['last_version'] = version_str
            version_json[stage]['build'] += 1
            version_str += '.%s' % version_json[stage]['build']
        slack_post(project, start_msg(project, branch, version_str, deploy=(stage == 'staging')))
        # Run the build
        popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/quasar-frontend/build/container.json'))
        popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/skywatch/repos/quasar-frontend')
        popen_cmd(('npm', 'install'), cwd='/skywatch/repos/quasar-frontend')
        popen_cmd(('grunt', 'build', '--env=%s' % stage), cwd='/skywatch/repos/quasar-frontend')
        popen_cmd(('packer', 'build', '-var', 'stage=%s' % stage, 'container.json'), cwd='/skywatch/repos/quasar-frontend/build/')
        with open('/skywatch/quasar_fe_version.json', 'w') as f:
            json.dump(version_json, f)
        popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/quasar-fe-%s' % stage))
        # Remove generated docker images
        popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/quasar-fe-%s)' % stage, shell=True)
        return version_str

    def build_quasar_api(project, branch, end_msg=True):
        stage = 'prod' if branch == 'master' else branch
        popen_cmd('git reset --hard HEAD && git fetch -p && git checkout %s && git pull' % branch, shell=True, cwd='/skywatch/repos/quasar-api')
        with open('/skywatch/quasar_api_version.txt', 'r') as f:
            version = int(f.read())
            version_str = '%s.0' % version
        slack_post(project, start_msg(project, branch, version_str, deploy=(stage == 'staging')))
        # Run the build
        popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/quasar-api/build/container.json'))
        popen_cmd(('gcloud', 'docker', 'pull', 'us.gcr.io/skywatch-app/quasar-api-base:latest'))
        popen_cmd(('packer', 'build', '-var', 'stage=%s' % stage, 'container.json'), cwd='/skywatch/repos/quasar-api/build/')
        with open('/skywatch/quasar_api_version.txt', 'w') as f:
            f.write(str(version + 1))
        popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/quasar-api-%s' % stage))
        # Remove generated docker images
        popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/quasar-api-%s)' % stage, shell=True)
        return version_str

    def build_public_quasar_api(project, branch, end_msg=True):
        stage = 'prod' if branch == 'master' else branch
        popen_cmd('git reset --hard HEAD && git fetch -p && git checkout %s && git pull' % branch, shell=True, cwd='/skywatch/repos/quasar-public-api')
        with open('/skywatch/public_quasar_api_version.txt', 'r') as f:
            version = int(f.read())
            version_str = '%s.0' % version
        slack_post(project, start_msg(project, branch, version_str, deploy=(stage == 'staging')))
        # Run the build
        popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/quasar-public-api/build/container.json'))
        popen_cmd(('gcloud', 'docker', 'pull', 'us.gcr.io/skywatch-app/quasar-api-base:latest'))
        popen_cmd(('packer', 'build', '-var', 'stage=%s' % stage, 'container.json'), cwd='/skywatch/repos/quasar-public-api/build/')
        with open('/skywatch/public_quasar_api_version.txt', 'w') as f:
            f.write(str(version + 1))
        popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/quasar-public-api-%s' % stage))
        # Remove generated docker images
        popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/quasar-public-api-%s)' % stage, shell=True)
        return version_str

    while True:
        request_json = q.get()
        # load decoded json from post
        try:
            data = json.loads(request_json)
        except ValueError:
            logging.info('Invalid JSON received:\n"%s"', request_json)
            continue
        logging.info('JSON received:\n%s', json.dumps(data, indent=4))

        try:
            m = re.search(r'git@.*?:(.*)\.git', data['repository']['url'])
            project = m.group(1).lower()
        except:
            project = None

        if (data['ref'] == 'refs/heads/master'):
            logging.debug('Push to master.')
            branch = 'master'
            try:
		# ------- MaxQ ----------
		if project == 'front-end/maxq':
                    # popen_cmd(('sh', '/remotex/update.sh'))
                    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout master && git pull', shell=True, cwd='/skywatch/repos/maxq')
                    # Run build for remotex
                    slack_post(project, start())
                    popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/skywatch/repos/maxq')
                    popen_cmd(('npm', 'install'), cwd='/skywatch/repos/maxq')
		    #popen_cmd(('grunt', 'sass'), cwd='/skywatch/repos/maxq')
                    popen_cmd(('grunt', 'build'), cwd='/skywatch/repos/maxq')
                    #popen_cmd(('cp', '-r', 'dist/views/.', 'dist/'), cwd='/skywatch/repos/maxq') 
		    slack_post(project, finish())
                    #popen_cmd('cp /remotex/remotex-frontend/app/images/cc-front.png /remotex/remotex-frontend/dist/images', shell=True)
                    #popen_cmd('cp /remotex/remotex-frontend/app/images/visa-cc.png /remotex/remotex-frontend/dist/images', shell=True)
                    ##popen_cmd('cp /remotex/remotex-frontend/app/images/map_pic.png /remotex/remotex-frontend/dist/images', shell=True)
                    with open('/skywatch/maxq-version.txt', 'r') as f:
                        version = int(f.read())
                        version_str = '%s.0' % version
                    slack_post(project, start_msg(project, branch, version_str))
                    logging.info('Build and deploy image for remotex-frontend, image version %s' % version_str)
                    # Run the build
                    popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/maxq/build/website.json'))
                    popen_cmd(('packer', 'build', 'website.json'), cwd='/skywatch/repos/maxq/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/maxq'))
                    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'maxq', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'maxq', '--update-period=20s', '--image=us.gcr.io/skywatch-app/maxq:%s' % version_str))
                    with open('/skywatch/maxq-version.txt', 'w') as f:
                        f.write(str(version + 1))
                    # Delete local docker images
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/maxq)', shell=True, critical=False)
                    slack_post(project, end_msg(project, branch, version_str, deploy=True))
		
		# ------- Remotex Frontend --------
		if project == 'front-end/remotex':
		    # popen_cmd(('sh', '/remotex/update.sh'))
		    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout master && git pull', shell=True, cwd='/remotex/remotex-frontend')
		    # Run build for remotex
                    slack_post(project, start())
		    popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/remotex/remotex-frontend')
                    popen_cmd(('npm', 'install'), cwd='/remotex/remotex-frontend')
                    popen_cmd(('grunt', 'build', '-v'), cwd='/remotex/remotex-frontend')
		    slack_post(project, finish())
		    popen_cmd('cp /remotex/remotex-frontend/app/images/cc-front.png /remotex/remotex-frontend/dist/images', shell=True)
                    popen_cmd('cp /remotex/remotex-frontend/app/images/visa-cc.png /remotex/remotex-frontend/dist/images', shell=True)
		    #popen_cmd('cp /remotex/remotex-frontend/app/images/map_pic.png /remotex/remotex-frontend/dist/images', shell=True)
		    with open('/remotex/frontend-version.txt', 'r') as f:
			version = int(f.read())
                        version_str = '%s.0' % version
		    slack_post(project, start_msg(project, branch, version_str))
		    logging.info('Build and deploy image for remotex-frontend, image version %s' % version_str)
		    # Run the build
                    # popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/remotex/remotex-frontend/build/frontend.json'))
                    f = open('/remotex/remotex-frontend/build/frontend.json', 'r+b')
		    f_content = f.read()
		    logging.info(version)
		    logging.info(version_str)
		    f_content = re.sub(r'%s.0' % str(version-1), r'%s' % version_str, f_content)
 		    f.seek(0)
		    f.truncate()
		    f.write(f_content)
		    f.close()
		    popen_cmd(('packer', 'build', 'frontend.json'), cwd='/remotex/remotex-frontend/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/remotex-frontend'))
		    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'remotex-frontend', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'remotex-frontend', '--update-period=20s', '--image=us.gcr.io/skywatch-app/remotex-frontend:%s' % version_str))
                    with open('/remotex/frontend-version.txt', 'w') as f:
                        f.write(str(version + 1))
		    # Delete local docker images
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/remotex-frontend)', shell=True, critical=False)
		    slack_post(project, end_msg(project, branch, version_str, deploy=True))
                
		# ---- Website ----
                if project == 'front-end/website':
                    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout master && git pull', shell=True, cwd='/skywatch/repos/website')
                    f = open('/skywatch/repos/website/build/nginx.conf', 'r+b')
                    f_content = f.read()
                    f_content = re.sub(r'%website.skywatch.co', r'skywatch.co', f_content)
                    f.seek(0)
                    f.truncate()
                    f.write(f_content)
                    f.close()
		    # Run build
                    slack_post(project, start())
	 	    popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/skywatch/repos/website')
                    popen_cmd(('npm', 'install'), cwd='skywatch/repos/website')
                    popen_cmd(('grunt', 'build', '--env=prod'), cwd='/skywatch/repos/website')
		    slack_post(project, finish())
		    with open('/skywatch/website_version.txt', 'r') as f:
                        version = int(f.read())
                        version_str = '%s.0' % version
                    slack_post(project, start_msg(project, branch, version_str))
                    logging.info('Build and deploy image for website, image version %s' % version_str)
                    # Run the build
                    popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/website/build/website.json'))
                    popen_cmd(('packer', 'build', 'website.json'), cwd='/skywatch/repos/website/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/website'))
                    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'website-cluster', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'website', '--update-period=20s', '--image=us.gcr.io/skywatch-app/website:%s' % version_str))
                    with open('/skywatch/website_version.txt', 'w') as f:
                        f.write(str(version + 1))
                    # Delete local docker images
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/website)', shell=True, critical=False)
                    slack_post(project, end_msg(project, branch, version_str, deploy=True))
                
		# ---- Quasar ----
                elif project == 'front-end/quasar':
                    version_str = build_quasar_fe(project, branch)
                    popen_cmd(('git', 'tag', '-a', version_str, '-m', 'Automated tag generated by build of Quasar version %s' % '.'.join(version_str.split('.')[:-1])), cwd='/skywatch/repos/quasar-frontend')
                    popen_cmd(('git', 'push', 'origin', '--tags'), cwd='/skywatch/repos/quasar-frontend')
                    slack_post(project, end_msg(project, branch, version_str))
                
		# ------ Front-end Admin------
		elif project == 'front-end/remotex-admin':
                    # This is the admin panel for both Quasar and RemoteX
                    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout master && git pull', shell=True, cwd='/skywatch/repos/remotex-admin')
                    with open('/skywatch/admin_version.txt', 'r') as f:
                        version = int(f.read())
                        version_str = '%s.0' % version
                    slack_post(project, start_msg(project, branch, version_str))
                    # Run the build
                    popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/remotex-admin/build/container.json'))
                    popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/skywatch/repos/remotex-admin')
                    popen_cmd(('npm', 'install'), cwd='/skywatch/repos/remotex-admin')
                    popen_cmd(('grunt', 'build', '--env=prod'), cwd='/skywatch/repos/remotex-admin')
                    popen_cmd(('packer', 'build', '-var', 'stage=prod', 'container.json'), cwd='/skywatch/repos/remotex-admin/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/quasar-admin'))
                    # Remove generated docker images
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/quasar-admin)', shell=True)
                    with open('/skywatch/admin_version.txt', 'w') as f:
                        f.write(str(version + 1))
                    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'skywatch', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'quasar-admin', '--update-period=20s', '--image=us.gcr.io/skywatch-app/quasar-admin:%s' % version_str))
                    slack_post(project, end_msg(project, branch, version_str, deploy=True))
                
		# ------ Quasar Api ------
		elif project == 'api/api':
                    version_str = build_quasar_api(project, branch)
                    slack_post(project, end_msg(project, branch, version_str))
                
		elif project == 'api/public-api':
		    version_str = build_public_quasar_api(project, branch)
		    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'skywatch', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'quasar-public-api-prod', '--update-period=20s', '--image=us.gcr.io/skywatch-app/quasar-public-api-prod:%s' % version_str))
                    slack_post(project, end_msg(project, branch, version_str))

		# ---- Supernova ----
                elif project == 'supernova/front-end':
                    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout master && git pull', shell=True, cwd='/skywatch/repos/supernova-frontend')
                    with open('/skywatch/supernova_fe_version.txt', 'r') as f:
                        version = int(f.read())
                        version_str = '%s.0' % version
                    slack_post(project, start_msg(project, branch, version_str))
                    # Run the build
                    popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/supernova-frontend/build/container.json'))
                    popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/skywatch/repos/supernova-frontend')
                    popen_cmd(('npm', 'install'), cwd='/skywatch/repos/supernova-frontend')
                    popen_cmd(('grunt', 'build', '--env=prod'), cwd='/skywatch/repos/supernova-frontend')
                    popen_cmd(('packer', 'build', '-var', 'stage=prod', 'container.json'), cwd='/skywatch/repos/supernova-frontend/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/supernova-fe-prod'))
                    # Remove generated docker images
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/supernova-fe-prod)', shell=True)
                    with open('/skywatch/supernova_fe_version.txt', 'w') as f:
                        f.write(str(version + 1))
                    slack_post(project, end_msg(project, branch, version_str))
                elif project == 'supernova/api':
                    with open('/skywatch/supernova_api_version.txt', 'r') as f:
                        version = int(f.read())
                        version_str = '%s.0' % version
                    slack_post(project, start_msg(project, branch, version_str))
                    # Run the build
                    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout master && git pull', shell=True, cwd='/skywatch/repos/supernova-api')
                    popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/supernova-api/build/container.json'))
                    popen_cmd(('gcloud', 'docker', 'pull', 'us.gcr.io/skywatch-app/supernova-api-base:latest'))
                    popen_cmd(('packer', 'build', '-var', 'stage=prod', 'container.json'), cwd='/skywatch/repos/supernova-api/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/supernova-api-prod'))
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/supernova-api-prod)', shell=True)
                    with open('/skywatch/supernova_api_version.txt', 'w') as f:
                        f.write(str(version + 1))
                    slack_post(project, end_msg(project, branch, version_str))
                else:
                    logging.debug('LOG: ignoring project "%s"' % project)
            except Exception as e:
               slack_post(project, 'An error occurred: %s' % str(e))
               logging.exception('Unhandled exception occurred')
            logging.info('----- Finished build -----')
        elif (data['ref'] == 'refs/heads/staging'):
            logging.debug('Push to staging.')
            branch = 'staging'
            try:
                if project == 'front-end/quasar':
                    version_str = build_quasar_fe(project, branch, end_msg=False)
                    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'skywatch', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'quasar-fe-staging', '--update-period=20s', '--image=us.gcr.io/skywatch-app/quasar-fe-staging:%s' % version_str))
                    slack_post(project, end_msg(project, branch, version_str, deploy=True))
                elif project == 'api/api':
                    version_str = build_quasar_api(project, branch, end_msg=False)
                    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'skywatch', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'quasar-api-staging', '--update-period=20s', '--image=us.gcr.io/skywatch-app/quasar-api-staging:%s' % version_str))
                    slack_post(project, end_msg(project, branch, version_str, deploy=True))
		elif project == 'api/public-api':
                    version_str = build_public_quasar_api(project, branch)
		    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'skywatch', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'quasar-public-api-stg', '--update-period=20s', '--image=us.gcr.io/skywatch-app/quasar-public-api-staging:%s' % version_str))
                    slack_post(project, end_msg(project, branch, version_str))
		else:
                    logging.debug('LOG: ignoring project "%s"' % project)
	    except Exception as e:
               slack_post(project, 'An error occurred: %s' % str(e))
               logging.exception('Unhandled exception occurred')
	    logging.info('----- Finished build -----')
        elif (data['ref'] == 'refs/heads/develop'):
	    logging.debug('Push to staging.')
	    branch = 'staging'
	    try:
		if project == 'front-end/website':
		    popen_cmd('git reset --hard HEAD && git fetch -p && git checkout develop && git pull', shell=True, cwd='/skywatch/repos/website-staging')
                    # Run build
                    slack_post(project, start(branch='staging'))
                    popen_cmd(('bower', 'install', '--allow-root', '--config.interactive=false'), cwd='/skywatch/repos/website-staging')
                    popen_cmd(('npm', 'install'), cwd='skywatch/repos/website-staging')
                    popen_cmd(('grunt', 'build', '-v'), cwd='/skywatch/repos/website-staging')
                    slack_post(project, finish(branch='staging'))
                    with open('/skywatch/website_staging_version.txt', 'r') as f:
                        version = int(f.read())
                        version_str = '%s.0' % version
                    slack_post(project, start_msg(project, branch, version_str))
                    logging.info('Build and deploy image for website, image version %s' % version_str)
                    # Run the build
                    # popen_cmd(('sed', '-i', 's/_VERSION_/%s/' % version_str, '/skywatch/repos/website-staging/build/website-staging.json'))
                    f = open('/skywatch/repos/website-staging/build/website-staging.json', 'r+b')
                    f_content = f.read()
                    f_content = re.sub(r'%s.0' % str(version-1), r'%s' % version_str, f_content)
		    f.seek(0)
                    f.truncate()
                    f.write(f_content)
                    f.close()
		    r = open('/skywatch/repos/website-staging/build/nginx.conf', 'r+b')
                    r_content = r.read()
		    r_content = re.sub(r'/skywatch/website/dist', r'/skywatch/website-staging/dist', r_content)
		    r.seek(0)
                    r.truncate()
                    r.write(r_content)
                    r.close()
		    popen_cmd(('packer', 'build', 'website-staging.json'), cwd='/skywatch/repos/website-staging/build/')
                    popen_cmd(('gcloud', 'docker', 'push', 'us.gcr.io/skywatch-app/website-staging'))
                    # Ensure kubectl will make changes to the correct cluster
                    popen_cmd(('gcloud', 'container', 'clusters', 'get-credentials', 'website-cluster', '--zone', 'us-central1-f'))
                    popen_cmd(('kubectl', 'rolling-update', 'website-staging', '--update-period=20s', '--image=us.gcr.io/skywatch-app/website-staging:%s' % version_str))
                    with open('/skywatch/website_staging_version.txt', 'w') as f:
                        f.write(str(version + 1))
                    # Delete local docker images
                    popen_cmd('docker rmi $(docker images -q us.gcr.io/skywatch-app/website-staging)', shell=True, critical=False)
                    slack_post(project, end_msg(project, branch, version_str, deploy=True))
		else:
                    logging.debug('LOG: ignoring project "%s"' % project)
                # TODO: Supernova staging build and deploy process?
            except Exception as e:
               slack_post(project, 'An error occurred: %s' % str(e))
               logging.exception('Unhandled exception occurred')
            logging.info('----- Finished build -----')
        else:
            logging.debug('Wrong branch. Waiting for next commit.\n')

if __name__ == '__main__':
    # accept port number as argument
    try:
        port_number = int(sys.argv[1])
    except:
        port_number = 8000

    worker = threading.Thread(target=after_request, args=(queue,))
    worker.daemon = True # If anyone knows how to kill the worker cleanly, please do so
    worker.start()
    logging.info('Starting Flask on port %s' % port_number)
    app.run(host='0.0.0.0', port=port_number, debug=True)
