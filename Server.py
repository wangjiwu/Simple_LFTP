import socket
import os
import struct
import threading
import queue
import time

#接受的缓存队列的最大大小
RCV_BUFFER_SIZE = 50
#socket接受的缓存大小
BUF_SIZE = 1040
#数据包的数据大小
FILE_BUF_SIZE = 1024
# socket端口
SERVER_PORT = 12000
# 服务器文件夹
SERVER_FOLDER = 'ServerFiles/'
#发送的缓存字典大小
SEND_BUFFER_SIZE = 50
#超时时间
MAX_TIME_OUT = 1

cwnd = 1
ssthresh = 64

#互斥锁 用于修改ssthresh值
mutex = threading.Lock()

# 传输文件时的数据包格式(序列号，确认号，文件结束标志，1024B的数据)
# pkt_value = (int seq, int ack, int end_flag 1024B的byte类型 data)
pkt_struct = struct.Struct('IIII1024s')

def timeout(base, nextseqnum, sendBuffer,server_socket,lastSendPacketNum, client_address ) :
    print("发送超时， 出现丢包, 重新发送分组")

    global cwnd
    global ssthresh

    mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer, server_socket, lastSendPacketNum,client_address])
    mytimer.start()

    if mutex.acquire(1):
        # 整除 保证没有小数
        ssthresh = cwnd // 2

        if (ssthresh < 1) :
            ssthresh = 1

        cwnd = 1
        print("更新cwnd值为" + str(cwnd), "  更新ssthresh值为" + str(ssthresh))
        mutex.release()



    print("重新 send packet:" + str(base) + "~" + str(nextseqnum - 1))
    for i in range (base, nextseqnum + 1):
        try :
            server_socket.sendto(sendBuffer[i], client_address)
            print ("重新发送packet: " + str(i))
        except:
            mytimer.cancel()

# 接收到lget命令，向客户端发送文件
def lget(server_socket, client_address, large_file_name):
    server_socket.setblocking(False)
    print("LFTP lget", client_address, large_file_name)
    pkt_count = 0
    # 发送数据包次数计数
    # 模式rb 以二进制格式打开一个文件用于只读。文件指针将会放在文件的开头。
    file_to_send = open(SERVER_FOLDER + large_file_name, 'rb')

    print('正在发送', large_file_name)

    # 全局变量初始化
    sendBuffer = {}
    base = 0
    nextseqnum = 0
    rwnd = 1
    global cwnd
    global ssthresh
    cwnd = 1
    add = 0
    ssthresh = 64
    lastOldPat = 0


    lastSendPacketNum = -1

    mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer, server_socket, lastSendPacketNum,client_address])

    end_flag = False
    # 用缓冲区循环发送数据包
    while True:

        # 如果接收到接收方的确认信息
        try:

            message, client_address = server_socket.recvfrom(BUF_SIZE)

            unpacked_message = pkt_struct.unpack(message)

            print("receive ack packet:" + str(unpacked_message[1]) + "    lastOldPat: " + str(lastOldPat))

            print("-------------------------------cwnd:", str(cwnd))

            newBase = int(unpacked_message[1]) + 1
            rwnd = int(unpacked_message[3])

            print("-------------------------------rwnd:", str(rwnd))

            if (newBase == lastSendPacketNum + 1):
                mytimer.cancel()

                break

            # 更新缓冲区  把已经确认的包从缓冲区清除
            print("packet " + str(base) + "~" + str(newBase - 1) + "从缓冲区删除")

            for i in (base - 1, newBase - 1):
                try:
                    del sendBuffer[i]
                    if cwnd > ssthresh:
                        if add >= cwnd:
                            cwnd += 1
                            add = 0
                        else:
                            add += 1
                    else:
                        cwnd += 1

                except:
                    pass

            base = newBase

            if (base == nextseqnum):
                mytimer.cancel()
            else:
                mytimer.cancel()
                mytimer = threading.Timer(MAX_TIME_OUT, timeout,
                                          [base, nextseqnum, sendBuffer, server_socket, lastSendPacketNum,client_address])
                mytimer.start()

        except socket.error:

            if end_flag:
                continue

            # print("此时rwnd为：" + str(rwnd) + " base = " + str(base) + "nextseqnum = " + str(nextseqnum))
            # 当传送的包num 小于base + 窗口值， 就能继续发送包

            if nextseqnum - base > rwnd:
                # print("接受方缓存存在限制 rwnd, 发送速率过快拒绝发送")
                continue
                pass

            elif nextseqnum >= base + SEND_BUFFER_SIZE:
                # print("发送方缓存存在限制 SEND_BUFFER_SIZE, 发送速率过快拒绝发送")
                continue
            elif nextseqnum - base > cwnd:
                # print("受拥塞控制限制，发送速率拒绝发送")
                continue
                pass
            ## 发送缓冲区所有包

            # for i in range (minRE_CW):
            else:
                data = file_to_send.read(FILE_BUF_SIZE)
                seq = pkt_count
                ack = pkt_count

                print("send packet:" + str(nextseqnum))

                # 将元组打包发送
                if str(data) != "b''":  # b''表示文件读完
                    end_flag = 0
                    # rnwd发送方没用到， 为-1
                    server_socket.sendto(pkt_struct.pack(*(nextseqnum, ack, end_flag, 1, data)), client_address)
                else:
                    end_flag = 1  # 发送的结束标志为1，表示文件已发送完毕
                    lastSendPacketNum = nextseqnum
                    # rnwd发送方没用到， 为-1
                    print("=============================" + str(lastSendPacketNum) + "============================== ")
                    server_socket.sendto(pkt_struct.pack(*(nextseqnum, ack, end_flag, 1, 'end'.encode('utf-8'))),
                                         client_address)

                # 把发送的包加入缓冲区, 便于重传
                print("packet " + str(nextseqnum) + "加入缓冲区")
                sendBuffer[nextseqnum] = pkt_struct.pack(*(nextseqnum, ack, end_flag, 1, data))

                # 当base和nextseqnum相等时， 开始计时
                if (base == nextseqnum):
                    mytimer = threading.Timer(MAX_TIME_OUT, timeout,
                                              [base, nextseqnum, sendBuffer, server_socket, lastSendPacketNum,client_address])
                    mytimer.start()
                nextseqnum = nextseqnum + 1
                pkt_count += 1

            lastOldPat = nextseqnum - 1

    print(large_file_name, '发送完毕，发送数据包的数量：' + str(pkt_count))


# 接收到lsend命令，客户端向服务端发送文件
def lsend(server_socket, client_address, large_file_name):
    file_to_recv = open(SERVER_FOLDER + large_file_name, 'wb')
    # 接收数据包次数计数
    pkt_count = 0
    expect_pkt = 0
    # 发送ACK 注意要做好所有准备(比如创建文件)后才向服务端发送ACK
    # server_socket.sendto('ACK'.encode('utf-8'), client_address)

    print('正在接收', large_file_name)
    # 发送接收允许
    server_socket.sendto('接收允许'.encode('utf-8'), client_address)
    # 开始接收数据包

    # 用缓冲区接收数据包
    buff = queue.Queue()
    server_socket.setblocking(False)
    end_flag = False
    flag = True
    rwnd = buff.qsize()
    while True:
        try:
            packed_data, client_address = server_socket.recvfrom(BUF_SIZE)

            unpacked_data = pkt_struct.unpack(packed_data)
            seq = unpacked_data[0]

            if seq < expect_pkt:
                continue
            if seq == 200 and flag:
                flag = False
                continue
            buff.put(packed_data)
            print("收到数据包" + str(seq))


        # 使用流控制确保在网络上传输的数据包不会大于BUFFSIZE
        except BlockingIOError:

            while not buff.empty():
                rwnd = RCV_BUFFER_SIZE - buff.qsize() - 1
                print("rwnd " + str(rwnd))
                pkt = buff.get()
                unpacked_pkt = pkt_struct.unpack(pkt)
                seq = unpacked_pkt[0]
                end_flag = unpacked_pkt[2]
                data = unpacked_pkt[4]
                print("处理数据包" + str(seq))
                if expect_pkt != seq:
                    while True:
                        try:
                            server_socket.sendto(pkt_struct.pack(*(1, expect_pkt - 1, 1, rwnd, "".encode('utf-8'))),
                                                 client_address)
                            print("发送ACK" + str(expect_pkt - 1))
                            break
                        except socket.error:
                            continue


                else:
                    if end_flag != 1:
                        pkt_count += 1
                        file_to_recv.write(data)
                        #time.sleep(0.1)
                        while True:
                            try:
                                server_socket.sendto(pkt_struct.pack(*(1, expect_pkt, 1, rwnd, "".encode('utf-8'))),
                                                     client_address)
                                print("发送ACK" + str(expect_pkt))
                                expect_pkt += 1
                                break
                            except socket.error:
                                continue

        if end_flag:
            break

    file_to_recv.close()
    print('成功接收的数据包数量：' + str(pkt_count))


def serve_client(client_address, message):
    # 创建新的服务端socket为客户端提供服务
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # 来自客户端的命令，格式为[lsend|lget]#large_file_name，因此文件命名不允许含有#
    cmd = message.decode('utf-8').split('$')[0]
    large_file_name = message.decode('utf-8').split('$')[1]

    if cmd == 'lget':
        # 文件不存在，并告知客户端
        if os.path.exists(SERVER_FOLDER + large_file_name) is False:
            server_socket.sendto('fileNotExists'.encode('utf-8'), client_address)
            # 关闭socket
            server_socket.close()
            return

        # 连接允许
        server_socket.sendto('连接允许'.encode('utf-8'), client_address)
        # 等待ACK
        message, client_address = server_socket.recvfrom(BUF_SIZE)
        print('来自', client_address, '的数据是: ', message.decode('utf-8'))

        lget(server_socket, client_address, large_file_name)
    elif cmd == 'lsend':
        # 连接允许
        server_socket.sendto('连接允许'.encode('utf-8'), client_address)
        # 等待ACK
        message, client_address = server_socket.recvfrom(BUF_SIZE)
        print('来自', client_address, '的数据是: ', message.decode('utf-8'))

        lsend(server_socket, client_address, large_file_name)

    # 关闭socket
    server_socket.close()


def main():
    # 检查接收文件夹是否存在
    if os.path.exists(SERVER_FOLDER) is False:
        print('创建文件夹', SERVER_FOLDER)
        os.mkdir(SERVER_FOLDER)

    server_main_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_main_socket.bind(('', SERVER_PORT))

    while True:
        print('正在运行的线程数量：', threading.activeCount())
        # 服务端主socket等待客户端发起连接
        print("等待客户端发起连接...")
        message, client_address = server_main_socket.recvfrom(BUF_SIZE)
        print('来自', client_address, '的数据是: ', message.decode('utf-8'))

        # 创建新的线程，处理客户端的请求
        new_thread = threading.Thread(target=serve_client, args=(client_address, message))
        new_thread.start()


if __name__ == "__main__":
    main()
