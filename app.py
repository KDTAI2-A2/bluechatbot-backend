from flask import Flask, json, request, jsonify, abort
import time
import requests
import asyncio
import asgiref


from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql.sqltypes import ARRAY
from dotenv import load_dotenv
import time
import os

app = Flask(__name__)

load_dotenv()

POSTGRES_ID=os.getenv("POSTGRES_ID")
POSTGRES_PW=os.getenv("POSTGRES_PW")
DATABASE_URL=os.getenv("DATABASE_URL")

# app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{POSTGRES_ID}:{POSTGRES_PW}@localhost/kakao-flask"


app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.debug = True

db = SQLAlchemy(app)


class Customer(db.Model):
    __tablename__="Customer"

    id = db.Column(db.Integer, primary_key=True)
    kakao_id = db.Column(db.Integer)
    datas = db.relationship('ChatList', backref='customer')

class ChatList(db.Model):
    __tablename__="ChatList"

    id = db.Column(db.Integer, primary_key=True)
    chat_open_date = db.Column(db.String())
    customer_id = db.Column(db.Integer, db.ForeignKey('Customer.id'), nullable=False)
    messages = db.relationship('Chat', backref='chatlist')

class Chat(db.Model):
    __tablename__='Chat'

    id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    timestamp = db.Column(db.DateTime)
    imotion = db.Column(db.String())
    words = db.Column(ARRAY(db.String))
    chatlist_id = db.Column(db.Integer, db.ForeignKey('ChatList.id'), nullable=False)
    


db.create_all()



wait_count = 0
message_list = []
count_start = False


def find_or_create_user(user_id):
    try:
        customer = db.session.query(Customer).filter(Customer.kakao_id==int(user_id)).one()
        return customer
    except:
        customer = Customer(kakao_id=int(user_id))
        db.session.add(customer)
        db.session.commit()
        return customer

def find_or_create_date(today, customer):
    try:
        chatlist = db.session.query(ChatList).with_parent(customer).filter(ChatList.chat_open_date == today).one()     
        return chatlist
    except:
        chatlist = ChatList(chat_open_date=today, customer=customer)
        db.session.add(chatlist)
        db.session.commit()
        return chatlist

# time_stamp:시간, imotion:숫자, words:단어 리스트, chatlist:귀속할 챗리스트
def create_chat(time_stamp, imotion, words, chatlist):
    chat = Chat(timestamp=time_stamp, imotion=imotion, words=words, chatlist=chatlist)
    db.session.add(chat)
    db.session.commit()
    return

def get_today():
    today = time.localtime(time.time())
    return f"{today.tm_year}-{today.tm_mon}-{today.tm_mday}"


def text_from_chat(request_data, imotion, words):
    user_id = request_data['userRequest']['user']['id']
    time_stamp = time.ctime(time.time())
    today = get_today()

    customer = find_or_create_user(user_id)

    chatlist = find_or_create_date(today, customer)
    
    create_chat(time_stamp, imotion, words, chatlist)    


async def waiting(body):
    global wait_count
    global message_list

    # hello_code가 실행될때마다 wait_count 가 0으로 초기화
    # 새로운 대화가 넘어오지 않으면 1초마나 wait_count가 1씩 누적
    while wait_count < 6:
        wait_count = wait_count + 1
        time.sleep(1)
        # 아무동작 없이 5초가 흐르면 누적된 대화 리스트를 합쳐 모델API로 보냄
        if wait_count > 4:
            global count_start
            count_start = False
            message_to_model = jsonify("".join(message_list))
            # API로 리턴 받은 대답을 리턴해줌
            imotion, words, reply = await requests.post('/AI/sendMessage/', message_to_model)
            # 대화 내용과 결과를 DB에 저장
            text_from_chat(body, imotion, words)

            # 대답후 사용자의 대화를 받기 위해 리스트 초기화
            message_list = []
            return reply

# 카톡으로부터 요청
@app.route('/backend/sendMessage',methods=['POST'])
async def get_massages_from_chatbot():
    global count_start
    global wait_count
    # 입력이 들어올때마다 카운트 0으로
    wait_count = 0

    # 넘어온 JSON에서 메세지 받아 임시 리스트에 append
    body = request.get_json()
    message_to_model = body['userRequest']['utterance']
    message_list.append(message_to_model)

    # 처음 대화가 시작되는 순간에만 사용하기 위해 count_start 를 바꿔줌
    # 두번째 말풍선부턴 실행되지 않음
    if count_start == False:
        count_start = True
        # waiting() 으로 완성된 문구를 리턴받음
        result = await waiting(body)
        return result

    return "loading..."



# 프론트로부터 요청
@app.route('/frontend/getUsers/')
def request_users_data():
    customers = db.session.query(Customer).all()
    data = []
    for i in customers:
        json = {"id": i.id, "kakao_id": i.kakao_id}
        data.append(json)
    return jsonify(data)

@app.route('/frontend/getUser/<int:id>/')
def request_user_data(id):
    customer = db.session.query(Customer).filter(Customer.kakao_id == id).one()
    data = []
    for date in customer.datas:
        json = {"id": id, "kakao_id":customer.kakao_id,"date":date.chat_open_date}
        data.append(json)
    return jsonify(data)

@app.route('/frontend/getUser/<int:id>/getDate/<date>/')
def request_date_data(id, date):
    imotions = {}
    words = {}

    customer = db.session.query(Customer).filter(Customer.kakao_id == id).one()
    date = db.session.query(ChatList).with_parent(customer).filter(ChatList.chat_open_date == date).one()

    for message in date.messages:
        try:
            imotions[str(message.imotion)] += 1
        except:
            imotions[str(message.imotion)] = 1
        for word in message.words:
            try:
                words[word] +=1
            except:
                words[word] = 1
    def f1(x):
        return x[0]

    sorted_imotions = sorted(imotions.items(), key=f1, reverse=True)
    sorted_words = sorted(words.items(), key=f1, reverse=True)

    return jsonify({"imotion_rank":sorted_imotions,"word_rank":sorted_words})


if __name__ == '__main__':
    app.run(debug=True)