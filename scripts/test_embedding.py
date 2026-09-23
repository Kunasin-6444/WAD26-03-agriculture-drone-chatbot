from app.rag.embedding import embed_text


text = """
ตารางแสดงความกว้างของพื้นที่ฉีดพ่นตามระดับความสูง

ความสูง (เมตร) | หน้ากว้าง (เมตรต่อหัว) | หน้ากว้างรวม (เมตรต่อ 3 หัว)

0.5 | 1.4 | 3.1
1.0 | 2.8 | 4.5
1.5 | 4.3 | 6.0
2.0 | 5.7 | 7.4
2.5 | 7.1 | 8.8
"""


vector = embed_text(text)

print("Embedding created successfully")
print("Dimensions:", len(vector))
print("First 10 values:", vector[:10])