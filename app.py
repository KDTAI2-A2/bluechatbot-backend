from flask import Flask, json, request, jsonify, abort
import time
from flask.wrappers import Response
from flask_cors.decorator import cross_origin
import requests
import asyncio
import asgiref
from flask_cors import CORS
from apscheduler.schedulers.blocking import BlockingScheduler



from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql.sqltypes import ARRAY
from dotenv import load_dotenv
import time
import os

app = Flask(__name__)


CORS(app)

load_dotenv()

POSTGRES_ID=os.getenv("POSTGRES_ID")
POSTGRES_PW=os.getenv("POSTGRES_PW")
DATABASE_URL=os.getenv("DB_URL")
NAVER_API=os.getenv("NAVER_API")

# app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{POSTGRES_ID}:{POSTGRES_PW}@localhost/kakao-flask"


app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.debug = True

db = SQLAlchemy(app)


class Customer(db.Model):
    __tablename__="Customer"

    id = db.Column(db.Integer, primary_key=True)
    kakao_id = db.Column(db.String())
    name = db.Column(db.String())
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
    user_message = db.Column(db.String())
    bot_message = db.Column(db.String())
    chatlist_id = db.Column(db.Integer, db.ForeignKey('ChatList.id'), nullable=False)
    

# 초기화
db.create_all()



wait_count = 0
message_list = []
count_start = False


def find_or_create_user(user_id, name):
    try:
        customer = db.session.query(Customer).filter(Customer.kakao_id==user_id).one()
        return customer
    except:
        customer = Customer(kakao_id=user_id, name=name)
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
def create_chat(time_stamp, imotion, words, chatlist, message_to_model, reply):
    chat = Chat(timestamp=time_stamp, imotion=imotion, words=words, chatlist=chatlist, user_message=message_to_model, bot_message=reply)
    db.session.add(chat)
    db.session.commit()
    return

def get_today():
    today = time.localtime(time.time())
    return f"{today.tm_year}-{today.tm_mon}-{today.tm_mday}"


def text_from_chat(request_data, imotion, words, message_to_model, reply, name):
    user_id = str(request_data['user'])
    print(user_id)
    time_stamp = time.ctime(time.time())
    today = get_today()

    customer = find_or_create_user(user_id, name)

    chatlist = find_or_create_date(today, customer)
    
    create_chat(time_stamp, imotion, words, chatlist, message_to_model, reply)    


async def waiting(body, name):
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
            message_join = "".join(message_list)
            message_to_model = json.dumps({"msg":message_join}, ensure_ascii=False).encode('utf-8')
            
            print(message_to_model, type(message_to_model))
            # API로 리턴 받은 대답을 리턴해줌
            result = requests.post('http://ec2-54-180-203-163.ap-northeast-2.compute.amazonaws.com/AI/sendMessage/', data=message_to_model)
            result = result.json()
            # 대화 내용과 결과를 DB에 저장
            imotion = result[0]
            words = result[1]
            reply = result[2]
            text_from_chat(body, imotion, words, message_join, reply, name)
            # 대답후 사용자의 대화를 받기 위해 리스트 초기화
            message_list = []
            return reply

# 네이버에 result 이름으로 메세지 발송
def send_to_naver(result, user_id):
    headers={
        'Content-Type': 'application/json;charset=UTF-8',
        'Authorization': NAVER_API,
    }
    data = {
        "event": "send",
        "user": user_id,
        "textContent":{
            "text":result
        }
    }
    message = json.dumps(data)
    response = requests.post('https://gw.talk.naver.com/chatbot/v1/event', headers=headers, data=message)
    print("시스템 응답코드: ",response.status_code)
    print("시스템 응답내용: ",response.text)
    return Response(status=200)

# 스케줄링
sched = BlockingScheduler()
@sched.scheduled_job('cron', second='10,30,50', id='scheduling')
def scheduling():
    # kakao_id의 사용자들 tuple형태로 반환
    users = db.session.query(Customer).filter(Customer.kakao_id).all()

    now_time = time.strftime("%S")

    if now_time == "10":
        comment = "좋은 아침입니다. 어떤하루를 보내실건가요?"
    elif now_time == "30":
        comment = "오늘 점심은 무엇을 드실건가요?"
    elif now_time == "50":
        comment = "오늘하루 어떠셨나요?"
    
    for i in users:
        send_to_naver(comment,i)
        print(f'scheduling : {time.strftime("%H:%M:%S")},',comment) 
 




# 카톡으로부터 요청
@app.route('/backend/sendMessage',methods=['POST'])
async def get_massages_from_chatbot():
    global count_start
    global wait_count
    # 입력이 들어올때마다 카운트 0으로
    wait_count = 0

    name= ""

    # 넘어온 JSON에서 메세지 받아 임시 리스트에 append
    body = request.get_json()
    message_to_model = body['textContent']['text']
    user_id = body['user']
    try:
        db.session.query(Customer).filter(Customer.kakao_id==user_id).one()
    except:
        # 아이디가 없다면 메세지를 스플릿 해서 /이름 항목을 찾아서 이름 등록시킴
        command = message_to_model.split(' ')
        if '/이름' == command[0]:
            name = command[1]
            find_or_create_user(user_id, name)
            return send_to_naver(f"환영합니다 {name}님", user_id)
        else:
            new_name_comment = "처음 사용이시라면 '/이름 홍길동' 양식으로 입력해주세요."
            send_to_naver(new_name_comment, body)
            return Response(status=200)
    else:
        # 이름을 찾으면 정상적으로 진행
        print(message_to_model)
        message_list.append(message_to_model)
        # 처음 대화가 시작되는 순간에만 사용하기 위해 count_start 를 바꿔줌
        # 두번째 말풍선부턴 실행되지 않음
        if count_start == False:
            count_start = True
            # waiting() 으로 완성된 문구를 리턴받음
            result = await waiting(body, name)
            send_to_naver(result, user_id)
            
        return Response(status=200)




@app.route('/')
def hello():
    return "hello"

# 프론트로부터 요청
@app.route('/frontend/getUsers/')
@cross_origin()
def request_users_data():
    customers = db.session.query(Customer).all()
    data = []
    for i in customers:
        json = {"id": i.id, "kakao_id": i.kakao_id, "name": i.name}
        data.append(json)
    return jsonify(data)

@app.route('/frontend/getUser/<id>/')
@cross_origin()
def request_user_data(id):
    request_id = str(id)
    customer = db.session.query(Customer).filter(Customer.kakao_id == request_id).one()
    data = []
    for date in customer.datas:
        imotion = {}
        for chat in date.messages:
            chat_imotion = str(chat.imotion)
            imotion[chat_imotion] = True
            
        imotions =[k for k in imotion.keys() ] 
        

        json = {"id": date.id, "kakao_id":customer.kakao_id,"dates":{"date":date.chat_open_date, "imotions": imotions}}
        data.append(json)
    return jsonify(data)

@app.route('/frontend/getUser/<id>/getDate/<date>/')
@cross_origin()
def request_date_data(id, date):
    imotions = {}
    words = {}
    usr_msg = []
    bot_msg = []

    request_id = str(id)

    date_id=str(date)

    customer = db.session.query(Customer).filter(Customer.kakao_id == request_id).one()
    date = db.session.query(ChatList).with_parent(customer).filter(ChatList.chat_open_date == date).one()

    for message in date.messages:
        try:
            usr_msg.append(message.user_message)
            bot_msg.append(message.bot_message)
        except:
            print("error")
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

    return jsonify({"date":date_id,"imotion_rank":sorted_imotions,"word_rank":sorted_words, "user_message": usr_msg, "bot_message": bot_msg} )


if __name__ == '__main__':
    app.run(debug=True)
    sched.start()