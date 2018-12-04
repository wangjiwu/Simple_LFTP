import socket
import re
import os
import struct
import threading
import datetime
import queue


#socket接受的缓存大小
BUF_SIZE = 1040
#数据包的数据大小
FILE_BUF_SIZE = 1024
#服务器端口号
SERVER_PORT = 12000
#接受的缓存队列的最大大小
RCV_BUFFER_SIZE = 50
#接收文件名
CLIENT_FOLDER = 'ClientFiles/'   # 接收文件夹
#发送的缓存字典大小
SEND_BUFFER_SIZE = 50
#超时时间
MAX_TIME_OUT = 0.1
cwnd = 1
ssthresh = 64

#互斥锁 用于修改ssthresh值
mutex = threading.Lock()

# 传输文件时的数据包格式(序列号，确认号，文件结束标志，rwnd，1024B的数据)
# pkt_struct = (int seq, int ack, int end_flag， int rwnd, 1024B的byte类型 data)
pkt_struct = struct.Struct('IIII1024s')


def timeout(base, nextseqnum, sendBuffer,client_socket,lastSendPacketNum, server_address ) :
    print("发送超时， 出现丢包, 重新发送分组")

    global cwnd
    global ssthresh

    #启动定时器
    mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer, client_socket, lastSendPacketNum, server_address])
    mytimer.start()

    #当进入超时操作时 阻塞控制 使得cwnd为1， ssthresh 为当时的cwnd的一半， 利用互斥锁使得更改ssthresh不会冲突
    if mutex.acquire(1):
        ssthresh = cwnd / 2
        #防止ssthresh变为负数
        if (ssthresh < 1) :
            ssthresh = 1
        cwnd = 1
        print("更新cwnd值为" + str(cwnd), "  更新ssthresh值为" + str(ssthresh))
        mutex.release()

    #重新发送缓冲区里的所有包
    print("重新 send packet:" + str(base) + "~" + str(nextseqnum - 1))
    for i in range (base, nextseqnum + 1):
        try :
            client_socket.sendto(sendBuffer[i], server_address)
            print ("重新发送packet: " + str(i))
        except:
            #如果缓冲区的包已经发完， 将停止发送

            mytimer.cancel()


def lsend(client_socket, server_address, large_file_name):
    print("LFTP lsend", server_address, large_file_name)
    # 发送数据包次数计数
    pkt_count = 0
    # 模式rb 以二进制格式打开一个文件用于只读。文件指针将会放在文件的开头。
    file_to_send = open(CLIENT_FOLDER + large_file_name, 'rb')

    # 发送ACK 注意要做好所有准备(比如打开文件)后才向服务端发送ACK
    client_socket.sendto('ACK'.encode('utf-8'), server_address)

    # 等待服务端的接收允许  client_socket为非阻塞模式， 所以要 while循环 一直等待接收允许
    while True :
        try:
            message, server_address = client_socket.recvfrom(BUF_SIZE)
            break
        except:
            pass


    print('来自', server_address, '的数据是: ', message.decode('utf-8'))
    print('正在发送', large_file_name)

    #发送方缓存  是用字典来存储的 key为包号， value为包
    sendBuffer = {}
    #base值，nextseqnum值， rwnd值，cwnd， ssthresh初始化
    base = 0
    nextseqnum = 0
    rwnd = 1
    global cwnd
    global ssthresh
    cwnd = 1
    ssthresh = 64

    #当进入阻塞避免时用于判断  什么时候给cwnd 加1
    add = 0
    # 发送的最后一个发送的包的包号， 用于判断 timeout
    lastSendPacketNum = -1

    #定时器定义
    mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer,client_socket,lastSendPacketNum, server_address])

    #文件最后标志， 如果是最后一个包 此值为True
    end_flag = False

    # 在while循环下  接受ACK包或者发送数据包
    while True:

        #如果接收到接收方的确认信息
        try:
            #解包  打印收到的ACK包号， cwnd值， rwnd值
            message, server_address = client_socket.recvfrom(BUF_SIZE)
            unpacked_message = pkt_struct.unpack(message)
            print("receive ack packet:" + str(unpacked_message[1]))
            print ("-------------------------------cwnd:", str(cwnd))
            #得到确认的包号值 和 更新rwnd值
            newBase = int(unpacked_message[1]) + 1
            rwnd = int(unpacked_message[3])

            print("--------------------------------rwnd:", str(rwnd))

            #如果确认了最后一个包， 跳出循环， 结束传输
            if (newBase == lastSendPacketNum + 1):
                mytimer.cancel()
                break

            #更新缓冲区  把已经确认的包从缓冲区清除
            print("packet " + str(base) + "~" + str(newBase - 1) + "从缓冲区删除")

            # 对确认的包进行删除， 删除从base到确认的包 之间的包全部从缓冲区删除
            for i in (base - 1, newBase - 1):
                try:
                    del sendBuffer[i]
                    #如果大于阈值 进入阻塞避免
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

            #更新base值
            base = newBase

            #如果缓冲区为0  停止定时器， 否则启动第三期
            if (base == nextseqnum):
                mytimer.cancel()
            else:

                mytimer.cancel()
                mytimer = threading.Timer(MAX_TIME_OUT, timeout, [base, nextseqnum, sendBuffer,client_socket, lastSendPacketNum, server_address])
                mytimer.start()

        #捕捉到socket.error 表明此时没有数据收到， 则发送数据
        except socket.error:

            #当传送的包num 小于base + 窗口值， 就能继续发送包， 这是流控制
            if nextseqnum - base > rwnd:
                #print("接受方缓存存在限制 rwnd, 发送速率过快拒绝发送")
                continue
                pass

            #当发送的缓存已经满了 不能发包
            elif nextseqnum >= base + SEND_BUFFER_SIZE  :
                #print("发送方缓存存在限制 SEND_BUFFER_SIZE, 发送速率过快拒绝发送")
                continue

            #当发送小于cwnd时不能发送， 阻塞控制
            elif nextseqnum - base > cwnd:
                #print("受拥塞控制限制，发送速率拒绝发送")
                continue
                pass

            #发送数据包
            else:

                data = file_to_send.read(FILE_BUF_SIZE)
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
                    break

                #把发送的包加入缓冲区, 便于重传
                print ("packet " + str(nextseqnum) + "加入缓冲区")
                sendBuffer[nextseqnum] = pkt_struct.pack(*(nextseqnum, ack, end_flag, 1, data))

                #当base和nextseqnum相等时， 开始计时
                if (base == nextseqnum) :
                    mytimer = threading.Timer(MAX_TIME_OUT, timeout,
                                              [base, nextseqnum, sendBuffer, client_socket, lastSendPacketNum, server_address])
                    mytimer.start()

                # nextseqnum自增， pkt_count自增
                nextseqnum = nextseqnum + 1
                pkt_count += 1


    print(large_file_name, '发送完毕，发送数据包的数量：' + str(pkt_count))


def lget(client_socket, server_address, large_file_name):
    file_to_recv = open(CLIENT_FOLDER + large_file_name, 'wb')
    # 接收数据包次数计数
    pkt_count = 0
    expect_pkt = 0
    # 发送ACK 注意要做好所有准备(比如创建文件)后才向服务端发送ACK

    print('正在接收', large_file_name)
    # 发送接收允许
    client_socket.sendto('接收允许'.encode('utf-8'), server_address)
    # 开始接收数据包

    # 用缓冲区接收数据包
    buff = queue.Queue()
    client_socket.setblocking(False)
    end_flag = False
    flag = True
    rwnd = buff.qsize()
    while True:
        try:
            packed_data, server_address = client_socket.recvfrom(BUF_SIZE)

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
                            client_socket.sendto(pkt_struct.pack(*(1, expect_pkt - 1, 1, rwnd, "".encode('utf-8'))),
                                                 server_address)
                            print("发送ACK" + str(expect_pkt - 1))
                            break
                        except socket.error:
                            continue


                else:
                    if end_flag != 1:
                        pkt_count += 1
                        file_to_recv.write(data)
                        # time.sleep(0.1)
                        print(str(rwnd))
                        while True:
                            try:
                                client_socket.sendto(pkt_struct.pack(*(1, expect_pkt, 1, rwnd, "".encode('utf-8'))),
                                                     server_address)
                                print("发送ACK" + str(expect_pkt))
                                expect_pkt += 1
                                break
                            except socket.error:
                                continue

        if end_flag:
            break

    file_to_recv.close()
    print('成功接收的数据包数量：' + str(pkt_count))


# 接收到lsend命令，客户端向服务端发送文件

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
    #cmd = "LFTP lsend 10.1.1.207 test1.mp4"
    #cmd = "LFTP lget 10.1.1.207 test2.mp4"

    cmd = "LFTP lsend 127.0.0.1 test6.mp4"
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


