from database import SessionLocal, QuestionPaper, init_db

def populate_papers():
    db = SessionLocal()
    papers_to_add = [
        QuestionPaper(department="CSE", semester="3rd", year="2022", paper_name="Discrete Mathematics", file_path="./papers/CSE/3rd/2022/DM.pdf"),
        QuestionPaper(department="CSE", semester="3rd", year="2022", paper_name="Data Structures", file_path="./papers/CSE/3rd/2022/DS.pdf"),
        QuestionPaper(department="CSE", semester="3rd", year="2023", paper_name="Discrete Mathematics", file_path="./papers/CSE/3rd/2023/DM.pdf"),
        QuestionPaper(department="IT", semester="5th", year="2021", paper_name="Operating Systems", file_path="./papers/IT/5th/2021/OS.pdf"),
        QuestionPaper(department="IT", semester="5th", year="2021", paper_name="Computer Networks", file_path="./papers/IT/5th/2021/CN.pdf"),
        QuestionPaper(department="ECE", semester="7th", year="2020", paper_name="Digital Signal Processing", file_path="./papers/ECE/7th/2020/DSP.pdf"),
    ]

    for paper in papers_to_add:
        existing_paper = db.query(QuestionPaper).filter(
            QuestionPaper.department == paper.department,
            QuestionPaper.semester == paper.semester,
            QuestionPaper.year == paper.year,
            QuestionPaper.paper_name == paper.paper_name
        ).first()
        if not existing_paper:
            db.add(paper)
            print(f"Added: {paper.paper_name} ({paper.department} {paper.semester} {paper.year})")
        else:
            print(f"Already exists: {paper.paper_name} ({paper.department} {paper.semester} {paper.year})")
    
    db.commit()
    db.close()
    print("Database population complete.")

if __name__ == "__main__":
    init_db()
    populate_papers() 