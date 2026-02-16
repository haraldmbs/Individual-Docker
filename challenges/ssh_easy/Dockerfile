FROM alpine:latest

RUN apk add --no-cache openssh \
    && ssh-keygen -A \
    && echo 'root:ctf' | chpasswd \
    && echo 'Welcome to the SSH Challenge!' > /etc/motd

# Allow root login for CTF (insecure by default, but intended for challenge)
RUN sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config

# Add flag
RUN echo "CTF{ssh_secure_shell_success}" > /root/flag.txt

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D", "-e"]
