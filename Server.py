import socket
import os
import struct
import threading
import queue
import time
RCV_BUFFER_SIZE = 50
BUF_SIZE = 1500
FILE_BUF_SIZE = 1024
SERVER_PORT = 12000
SERVER_FOLDER = 'ServerFiles/'

# 传输文件时的数据包格式(序列号，确认号，文件结束标志，1024B的数据)
# pkt_value = (int seq, int ack, int end_flag 1024B的byte类型 data)
pkt_struct = struct.Struct('IIII1024s')

def recv_ACK(server_socket):
    while True:
        try:
            data, client_address = server_socket.recvfrom(BUF_SIZE)
            unpacked_data = pkt_struct.unpack(data)
            print("接收ACK", unpacked_data[0])
        except:
            break



# 接收到lget命令，向客户端发送文件
def lget(server_socket, client_address, large_file_name):
    print('正在发送', large_file_name)
    # 模式rb 以二进制格式打开一个文件用于只读。文件指针将会放在文件的开头。
    file_to_send = open(SERVER_FOLDER + large_file_name, 'rb')
    # 发送数据包次数计数
    pkt_count = 0

    thread = threading.Thread(target=recv_ACK, args=(server_socket, ))
    thread.start()
    # 用缓冲区循环发送数据包

    while True:
        data = file_to_send.read(FILE_BUF_SIZE)
        seq = pkt_count
        ack = pkt_count

        # 将元组打包发送
        if str(data) != "b''":  # b''表示文件读完
            end_flag = 0
            server_socket.sendto(pkt_struct.pack(*(seq, ack, end_flag, 0, data)), client_address)
        else:
            end_flag = 1    # 发送的结束标志为1，表示文件已发送完毕
            server_socket.sendto(pkt_struct.pack(*(seq, ack, end_flag, 0, 'end'.encode('utf-8'))), client_address)
            break
        # 等待客户端ACK
        print("发送seq" + str(seq))


        pkt_count += 1

    file_to_send.close()
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


        #使用流控制确保在网络上传输的数据包不会大于BUFFSIZE
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
                            server_socket.sendto(pkt_struct.pack(*(1, expect_pkt - 1, 1, rwnd, "".encode('utf-8'))), client_address)
                            print("发送ACK" + str(expect_pkt - 1))
                            break
                        except socket.error:
                            continue


                else:
                    if end_flag != 1:
                        pkt_count += 1
                        file_to_recv.write(data)
                        #time.sleep(0.1)
                        print(str(rwnd))
                        while True:
                            try:
                                server_socket.sendto(pkt_struct.pack(*(1, expect_pkt, 1, rwnd, "".encode('utf-8'))), client_address)
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
    cmd = message.decode('utf-8').split('#')[0]
    large_file_name = message.decode('utf-8').split('#')[1]

    if cmd == 'lget':
        # 文件不存在，并告知客户端
        if os.path.exists(SERVER_FOLDER + large_file_name) is False:
            server_socket.sendto('fileNotExists'.encode('utf-8'), client_address)
            # 关闭socket
            server_socket.close()
            return

        # TODO: 在此要把各样工作准备好，再发送连接允许

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

        # TODO: 在此要把各样工作准备好，再发送接收允许(在lsend内)

        lsend(server_socket, client_address, large_file_name)

    # 关闭socket


    server_socket.close()


def main():
    # 检查接收文件夹是否存在
    if os.path.exists(SERVER_FOLDER) is False:
        print('创建文件夹', SERVER_FOLDER)
        os.mkdir(SERVER_FOLDER)

    # 创建服务端主socket，周知端口号为SERVER_PORT
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
