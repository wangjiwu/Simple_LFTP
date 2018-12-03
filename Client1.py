import socket
import re
import os
import struct
import threading
import datetime
BUF_SIZE = 1500
FILE_BUF_SIZE = 1024
SERVER_PORT = 12000
CLIENT_FOLDER = 'ClientFiles/'   # 接收文件夹
N = 50
MAX_TIME_OUT = 0.1
cwnd = 1
ssthresh = 64
mutex = threading.Lock()


# 传输文件时的数据包格式(序列号，确认号，文件结束标志，1024B的数据)
# pkt_value = (int seq, int ack, int end_flag 1024B的byte类型 data)

pkt_struct = struct.Struct('IIII1024s')

server_address_tmp = "127.0.0.1",55222


def timeout(base, nextseqnum, sendBuffer,client_socket,lastSendPacketNum ) :
    print("发送超时， 出现丢包, 重新发送分组")

    global cwnd
    global ssthresh

    mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer, client_socket, lastSendPacketNum])
    mytimer.start()

    # if (len(sendBuffer) == 1) :
    #     print("缓冲区为空， 重发数据包确认成功，停止重发")
    #     mytimer.cancel()
    if mutex.acquire(1):
        ssthresh = cwnd / 2

        if (ssthresh < 1) :
            ssthresh = 1

        cwnd = 1
        print("更新cwnd值为" + str(cwnd), "  更新ssthresh值为" + str(ssthresh))
        mutex.release()



    print("重新 send packet:" + str(base) + "~" + str(nextseqnum - 1))
    for i in range (base, nextseqnum + 1):
        try :
            client_socket.sendto(sendBuffer[i], server_address_tmp)
            print ("重新发送packet: " + str(i))
        except:
            mytimer.cancel()


def lsend(client_socket, server_address, large_file_name):
    print("LFTP lsend", server_address, large_file_name)
    pkt_count = 0
    # 发送数据包次数计数
    # 模式rb 以二进制格式打开一个文件用于只读。文件指针将会放在文件的开头。
    file_to_send = open(CLIENT_FOLDER + large_file_name, 'rb')

    # 发送ACK 注意要做好所有准备(比如打开文件)后才向服务端发送ACK
    client_socket.sendto('ACK'.encode('utf-8'), server_address)

    # 等待服务端的接收允许
    while True :
        try:
            message, server_address = client_socket.recvfrom(BUF_SIZE)
            break
        except:
            pass


    print('来自', server_address, '的数据是: ', message.decode('utf-8'))

    print('正在发送', large_file_name)

    #全局变量初始化
    sendBuffer = {}
    base = 0
    nextseqnum = 0
    rwnd = 1
    global cwnd
    global ssthresh
    cwnd = 1
    ssthresh = 64
    cansend = True
    lastOldPat = 0

    #timeout时间为两秒

    lastSendPacketNum = -1

    mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer,client_socket,lastSendPacketNum])



    end_flag = False
        # 用缓冲区循环发送数据包
    while True:

        #如果接收到接收方的确认信息
        try:

            message, server_address = client_socket.recvfrom(BUF_SIZE)

            unpacked_message = pkt_struct.unpack(message)

            print("receive ack packet:" + str(unpacked_message[1]) + "    lastOldPat: "  + str(lastOldPat))

            if lastOldPat == unpacked_message[1]:

                #如果到达阈值  变成阻塞避免模式
                if (cwnd * 2 > ssthresh):
                    cwnd += 1
                #否则进入慢启动模式
                else:
                    cwnd *= 2

                cansend = True


            print ("-------------------------------cwnd:", str(cwnd))

            newBase = int(unpacked_message[1]) + 1
            rwnd = int(unpacked_message[3])

            print("--------------------------------rwnd:", str(rwnd))

            if (newBase == lastSendPacketNum + 1):
                mytimer.cancel()
                break


            #更新缓冲区  把已经确认的包从缓冲区清除
            print("packet " + str(base) + "~" + str(newBase - 1) + "从缓冲区删除")

            for i in (base - 1, newBase - 1):
                try:
                    del sendBuffer[i]
                except:
                    pass

            base = newBase

            if (base == nextseqnum):
                mytimer.cancel()
            else:
                mytimer.cancel()
                mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer,client_socket, lastSendPacketNum])
                mytimer.start()


        except socket.error:
            if not cansend:
                continue
            if end_flag:
                continue

            #print("此时rwnd为：" + str(rwnd) + " base = " + str(base) + "nextseqnum = " + str(nextseqnum))
            #当传送的包num 小于base + 窗口值， 就能继续发送包

            minRE_CW = min(rwnd, cwnd)

            if nextseqnum - base > rwnd:
                #print("接受方缓存存在限制 rwnd, 发送速率过快拒绝发送")
                continue

            elif nextseqnum >= base + N  :
                #print("发送方缓存存在限制 N, 发送速率过快拒绝发送")
                continue

            ## 发送缓冲区所有包

            for i in range (minRE_CW):

                data = file_to_send.read(FILE_BUF_SIZE)
                seq = pkt_count
                ack = pkt_count

                print("send packet:" + str(nextseqnum))

                # 将元组打包发送
                if str(data) != "b''":  # b''表示文件读完
                    end_flag = 0
                    #rnwd发送方没用到， 为-1
                    client_socket.sendto(pkt_struct.pack(*(nextseqnum, ack, end_flag, 1, data)), server_address)
                else:
                    end_flag = 1  # 发送的结束标志为1，表示文件已发送完毕
                    lastSendPacketNum = nextseqnum
                    # rnwd发送方没用到， 为-1
                    print ("=============================" +  str(lastSendPacketNum) + "============================== ")
                    client_socket.sendto(pkt_struct.pack(*(nextseqnum, ack, end_flag, 1 , 'end'.encode('utf-8'))), server_address)

                #把发送的包加入缓冲区, 便于重传
                print ("packet " + str(nextseqnum) + "加入缓冲区")
                sendBuffer[nextseqnum] = pkt_struct.pack(*(nextseqnum, ack, end_flag, 1, data))


                #当base和nextseqnum相等时， 开始计时
                if (base == nextseqnum) :
                    mytimer = threading.Timer(MAX_TIME_OUT, timeout,
                                              [base, nextseqnum, sendBuffer, client_socket, lastSendPacketNum])
                    mytimer.start()
                nextseqnum = nextseqnum + 1
                pkt_count += 1

            lastOldPat = nextseqnum - 1
            cansend = False





    print(large_file_name, '发送完毕，发送数据包的数量：' + str(pkt_count))


def lget(client_socket, server_address, large_file_name):
    print("LFTP lget", server_address, large_file_name)
    # 创建文件。模式wb 以二进制格式打开一个文件只用于写入。如果该文件已存在则打开文件，
    # 并从开头开始编辑，即原有内容会被删除。如果该文件不存在，创建新文件。
    file_to_recv = open(CLIENT_FOLDER + large_file_name, 'wb')
    # 接收数据包次数计数
    pkt_count = 0

    # 发送ACK 注意要做好所有准备(比如创建文件)后才向服务端发送ACK
    client_socket.sendto('ACK'.encode('utf-8'), server_address)

    print('正在接收', large_file_name)
    # 开始接收数据包
    while True:
        # 用缓冲区接收数据包
        packed_data, server_address = client_socket.recvfrom(BUF_SIZE)
        # 解包，得到元组
        unpacked_data = pkt_struct.unpack(packed_data)
        end_flag = unpacked_data[2]
        data = unpacked_data[3]

        if end_flag != 1:
            file_to_recv.write(data)
        else:
            break  # 结束标志为1,结束循环
        # 向服务端发送ACK
        client_socket.sendto('ACK'.encode('utf-8'), server_address)
        pkt_count += 1

    file_to_recv.close()
    print('成功接收的数据包数量：' + str(pkt_count))


def connection_request(client_socket, server_addr, cmd, large_file_name):

    # 若要发送的文件不存在，退出程序
    if cmd == 'lsend' and (os.path.exists(CLIENT_FOLDER + large_file_name) is False):
        print('要发送的文件不存在，退出程序')
        exit(2)

    # 三次握手
    # 连接请求，格式为[lsend|lget]#large_file_name，因此文件命名不允许含有#
    client_socket.sendto((cmd + '#' + large_file_name).encode('utf-8'), server_addr)
    # 接收连接允许报文

    while True :
        try:
            message, server_address = client_socket.recvfrom(BUF_SIZE)
            break
        except:
            pass


    print('来自', server_address, '的数据是: ', message.decode('utf-8'))

    global server_address_tmp
    server_address_tmp = server_address

    # 若服务端该文件不存在，退出程序
    if message.decode('utf-8') == 'fileNotExists':
        exit(2)

    # 注意要做好所有准备(比如创建文件)后才向服务端发送ACK
    if cmd == 'lget':
        lget(client_socket, server_address, large_file_name)
    elif cmd == 'lsend':
        lsend(client_socket, server_address, large_file_name)


def read_command(client_socket):
    #print('请输入命令: LFTP [lsend | lget] server_address large_file_name')
    pattern = re.compile(r"(LFTP) (lsend|lget) (\S+) (\S+)")
    # LFTP lget 127.0.0.1 CarlaBruni.mp3
    # LFTP lsend 127.0.0.1 CarlaBruni.mp3
    cmd = "LFTP lsend 118.25.215.11 test1.mp4"
    #cmd = "LFTP lsend 127.0.0.1 test.mp4"
    match = pattern.match(cmd)
    if match:
        cmd = match.group(2)
        server_ip = match.group(3)
        large_file_name = match.group(4)
        connection_request(client_socket, (server_ip, SERVER_PORT), cmd, large_file_name)
    else:
        print('[Error] Invalid command!')


def main():
    # 检查接收文件夹是否存在

    start = datetime.datetime.now()


    if os.path.exists(CLIENT_FOLDER) is False:
        print('创建文件夹', CLIENT_FOLDER)
        os.mkdir(CLIENT_FOLDER)

    # 创建客户端socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.setblocking(False)

    # 客户端输入命令
    read_command(client_socket)

    end = datetime.datetime.now()

    print ("总共花费时间为:" + str((end-start).total_seconds()) + "秒")

    # 关闭客户端socket
    client_socket.close()




if __name__ == "__main__":
    main()



