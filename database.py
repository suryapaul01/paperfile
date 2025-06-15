from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

# Association table for many-to-many relationship between users and papers
user_papers = Table('user_papers', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('paper_id', Integer, ForeignKey('papers.id'))
)

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    stars = Column(Integer, default=0)
    purchased_papers = relationship("QuestionPaper", secondary=user_papers, backref="purchased_by")

class QuestionPaper(Base):
    __tablename__ = 'papers'
    
    id = Column(Integer, primary_key=True)
    department = Column(String)
    semester = Column(Integer)
    year = Column(Integer)
    paper_name = Column(String)
    file_url = Column(String)  # Firebase Storage URL
    price = Column(Integer, default=5)

# Database setup
def init_db():
    engine = create_engine('sqlite:///bot.db')
    Base.metadata.create_all(engine)
    return engine

SessionLocal = sessionmaker(bind=init_db())

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 