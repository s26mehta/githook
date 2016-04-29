#!/usr/bin/env bash

################################################################################
#                                                                              #
# Script to update and deploy front-end of RemoteX application                 #
#                                                                              #
# Owen Littlejohns, 2016-Feb-11 (based heavily on code by Ryan Ovas)           #
#                                                                              #
# Note - format of long commands is cmd1 || { cmd2; cmd3; cmd4}                #
#        (i.e.: try cmd1, if fails then do all of cmd2, cmd3 and cm4, where:   #
#            cmd2 - make entry in log file                                     #
#            cmd3 - send notification to Slack                                 #
#            cmd4 - Make error flag = 1                                        #
# To do:                                                                       #
#        - Check whether this is the slow or fast way (Dylan update method)    #
#                                                                              #
################################################################################

# Global variables
repo_dir="/remotex/remotex-frontend"
build_dir="/skywatch/logs"
build_branch="master"
error_flag=0
image_version=$(</remotex/frontend-version.txt)

# Log the start of the build process
echo "Build began: "`date +%Y-%m-%d-%H:%M:%S` >> ${build_dir}githook.log
curl -X POST -H 'Content-type: application/json' --data '{"text":"Build started for master" ,"icon_emoji": ":hourglass:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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

# Change to build directory
cd ${repo_dir} || { echo "error running cd ${build_dir}" >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Unable to change directory","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }

# Checkout specified branch of the RemoteX front-end repo
git checkout ${build_branch} || { echo "error running git checkout ${build_branch}" >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Unable to checkout correct branch","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }

# Fetch repo
git fetch || { echo "error running git fetch" >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Error with git fetch","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }

# Sync repo to remote version (hard)
git reset --hard origin/${build_branch} || { echo "error running git reset --hard origin/${build_branch}" >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Error with git reset --hard","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }

# Install dependencies
script -q -c "bower install --allow-root --config.interactive=false" || { echo 'error running script -q -c "bower install --allow-root"' >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Error with bower install","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }

# Install packages
script -q -c "npm install" || { echo 'error running script -q -c "npm install"' >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Error with npm install","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }

# Build the front-end
script -q -c "grunt build --env=prod" || { echo 'error running script -q -c "grunt build"' >> ${build_dir}githook.log; curl -X POST -H 'Content-type: application/json' --data '{"text":"Error with grunt build","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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; error_flag=1; }


rm typescript

# Log final message (success/failure) to log file and to Slack.
if [ "${error_flag}" -eq "1" ];
then
    echo "Build Failure: "`date +%Y-%m-%d-%H:%M:%S` >> ${build_dir}githook.log
    curl -X POST -H 'Content-type: application/json' --data '{"text":"Build Unsuccessful","icon_emoji": ":no_entry:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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;
else
    echo "Build Success: "`date +%Y-%m-%d-%H:%M:%S` >> ${build_dir}githook.log
    curl -X POST -H 'Content-type: application/json' --data '{"text":"Master build Successful","icon_emoji": ":white_check_mark:", "username": "RemoteX Front-End", "channel": "#remotex-build"}' https://hooks.slack.com/services/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;
fi
