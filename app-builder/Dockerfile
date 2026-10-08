# App Builder image: Node 22 + JDK 17 + Gradle 8.9 + Android SDK (platform 34).
# Needs outbound access to dl.google.com, services.gradle.org, maven.google.com and repo.maven.apache.org at build time.
FROM node:22-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      openjdk-17-jdk-headless unzip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV ANDROID_HOME=/opt/android-sdk
ENV GRADLE_HOME=/opt/gradle
ENV PATH="${GRADLE_HOME}/bin:${ANDROID_HOME}/cmdline-tools/latest/bin:${PATH}"

RUN curl -fsSL https://services.gradle.org/distributions/gradle-8.9-bin.zip -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt && mv /opt/gradle-8.9 ${GRADLE_HOME} && rm /tmp/gradle.zip

RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
    && curl -fsSL https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -o /tmp/cmd.zip \
    && unzip -q /tmp/cmd.zip -d ${ANDROID_HOME}/cmdline-tools \
    && mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
    && rm /tmp/cmd.zip \
    && yes | sdkmanager --licenses > /dev/null \
    && sdkmanager "platforms;android-34" "build-tools;34.0.0"

WORKDIR /app
COPY package.json ./
COPY server ./server
COPY web ./web

ENV PORT=3000 DATA_DIR=/data
VOLUME /data
EXPOSE 3000
CMD ["node", "server/src/index.js"]
