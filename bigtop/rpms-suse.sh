#!/bin/bash

set -e

source build-scripts/lib.sh

BTBRANCH=$(source HDP_variables.sh &>/dev/null; echo $bigtopbranch)
BTEXPORT=$(source HDP_variables.sh &>/dev/null; echo $bigtopexport)
BRANCH=$(source HDP_variables.sh &>/dev/null; echo $huebranch)
REPODIR="$BTEXPORT/build/hue/rpm/RPMS/x86_64"

echo "Building RPMS for Hue branch '$BRANCH' with bigtop branch '$BTBRANCH'"
echo
echo "=========================="
echo "Prepare environment"
echo

# fix /dev/fd
[ ! -e /dev/fd ] && sudo ln -s /proc/self/fd /dev/fd

sudo zypper install -y createrepo git rpmbuild mysql-devel openldap2-devel python-simplejson sqlite-devel\
    python-setuptools python-devel cyrus-sasl-devel cyrus-sasl-gssapi gcc gcc-c++ krb5-devel\
    libxml2-devel libxslt-devel mysql krb5 lsb-release curl

sudo easy_install boto


WORKSPACE="`pwd`"

MVN_VERSION=3.1.1

cd $HOME
[ ! -f apache-maven-$MVN_VERSION-bin.tar.gz ] && wget http://apache-mirror.telesys.org.ua/maven/maven-3/$MVN_VERSION/binaries/apache-maven-$MVN_VERSION-bin.tar.gz
sudo tar xzf apache-maven-$MVN_VERSION-bin.tar.gz -C /usr/local
cd /usr/local
sudo ln -sf apache-maven-$MVN_VERSION maven 

cd $HOME
pwd
mkdir -p tools/maven tools/jdk64_31
[ ! -e tools/maven/latest ] && ln -sf  /usr/local/maven tools/maven/latest
[ ! -e tools/jdk64_31/latest ] && ln -sf  /usr/lib64/jvm/java-1.6.0-openjdk tools/jdk64_31/latest

export M2_HOME=/usr/local/maven
export PATH=${M2_HOME}/bin:${PATH}
export PATH="$PATH:/usr/lib/mit/bin:/usr/lib/mit/sbin"
export JAVA_HOME=/usr/lib64/jvm/java-1.6.0-openjdk


echo "=========================="
echo "Build"
echo

rm -rf "$REPODIR"
cd "$WORKSPACE"

sh bigtop_build.sh hue

echo
echo "DONE!"
echo "=========================="
echo
echo "=========================="
echo "Creating repository..."
echo

createrepo "$REPODIR"

echo "=========================="
echo "Uploading artefacts to S3"
echo

ls -R $REPODIR

python build-scripts/upload.py "repo/$(get_s3_directory)/$BRANCH/bigtop/$1" "$REPODIR" build-scripts/aws_credentials.json

rm -rf output
cp -R "$REPODIR" output