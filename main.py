from flask import Flask, Response, jsonify, render_template
from ultralytics import YOLO
import cv2
import numpy as np
import os
import math
from collections import defaultdict

app = Flask(__name__)
model = YOLO('yolov8m.pt')
cap = cv2.VideoCapture('test.mp4')

if not os.path.exists('ihlaller'):
    os.makedirs('ihlaller')

canli_veri = {
    "toplam_ihlal": 0,
    "tehditler": []
}

cizilen_noktalar = []

def alan_ciz(event, x, y, flags, param):
    global cizilen_noktalar
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(cizilen_noktalar) < 4:
            cizilen_noktalar.append((x, y))

ret, ilk_kare = cap.read()
if not ret:
    print("Video okunamadı!")
    exit()

cv2.namedWindow('Taktik Alan Belirleme')
cv2.setMouseCallback('Taktik Alan Belirleme', alan_ciz)

print(">>> FARE İLE 4 KÖŞE SEÇİN. BİTİNCE 'ENTER'A BASIN. SIFIRLAMAK İÇİN 'C'YE BASIN.")

while True:
    temp_kare = ilk_kare.copy()
    
    for i, pt in enumerate(cizilen_noktalar):
        cv2.circle(temp_kare, pt, 6, (0, 0, 255), -1)
        if i > 0:
            cv2.line(temp_kare, cizilen_noktalar[i-1], pt, (0, 0, 255), 2)
            
    if len(cizilen_noktalar) == 4:
        cv2.line(temp_kare, cizilen_noktalar[3], cizilen_noktalar[0], (0, 0, 255), 2)
        cv2.putText(temp_kare, "ALAN HAZIR! BASLAMAK ICIN 'ENTER'A BASIN", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)
    else:
        cv2.putText(temp_kare, f"LUTFEN {4 - len(cizilen_noktalar)} NOKTA DAHA SECIN", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

    cv2.imshow('Taktik Alan Belirleme', temp_kare)
    
    key = cv2.waitKey(1) & 0xFF
    if key == 13 and len(cizilen_noktalar) == 4:  
        break
    elif key == ord('c') or key == ord('C'):  
        cizilen_noktalar = []

cv2.destroyWindow('Taktik Alan Belirleme')

zone_pts = np.array(cizilen_noktalar, dtype=np.int32).reshape((-1, 1, 2))

def generate_frames():
    global canli_veri
    kaydedilen_idler = set()
    track_history = defaultdict(lambda: [])
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        frame_count += 1
        if frame_count % 2 != 0:
            continue

        clean_frame = frame.copy()

        results = model.track(frame, persist=True, tracker="bytetrack.yaml", imgsz=1088, conf=0.45, classes=[2, 3, 5, 7], stream=True)

        aktif_hedeler_bilgisi = []

        for r in results:
            annotated_frame = r.plot()
            cv2.polylines(annotated_frame, [zone_pts], isClosed=True, color=(0, 0, 255), thickness=3)
            cv2.putText(annotated_frame, 'YASAK BOLGE', (zone_pts[0][0][0], zone_pts[0][0][1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

            if r.boxes is not None and r.boxes.id is not None:
                boxes = r.boxes.xyxy.cpu().numpy()
                ids = r.boxes.id.cpu().numpy().astype(int)
                cls_indices = r.boxes.cls.cpu().numpy().astype(int)

                for box, obj_id, cls_idx in zip(boxes, ids, cls_indices):
                    x1, y1, x2, y2 = map(int, box)
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)

                    track = track_history[obj_id]
                    track.append((cx, cy))

                    if len(track) > 30:
                        track.pop(0)

                    points = np.hstack(track).astype(np.int32).reshape(-1, 1, 2)
                    cv2.polylines(annotated_frame, [points], isClosed=False, color=(0, 255, 255), thickness=2)
                    
                    tahmini_hiz = 0

                    if len(track) >= 2:
                        prev_cx, prev_cy = track[-2]
                        pixel_distance = math.hypot(cx - prev_cx, cy - prev_cy)
                        tahmini_hiz = int(pixel_distance * 3.5)
                        
                    sinif_adi = model.names[cls_idx].upper()
                    
                    if obj_id in kaydedilen_idler and tahmini_hiz > 2:
                        aktif_hedeler_bilgisi.append({"id": int(obj_id), "sinif": sinif_adi, "hiz": tahmini_hiz})
        
                    inside = cv2.pointPolygonTest(zone_pts, (cx, cy), False)

                    if inside >= 0:
                        cv2.circle(annotated_frame, (cx, cy), 10, (0, 0, 255), -1)
                        cv2.putText(annotated_frame, f"ALARM! HEDEF ID:{obj_id}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 4)
                        
                        if obj_id not in kaydedilen_idler:
                            canli_veri["toplam_ihlal"] += 1
                            tehdit_fotosu = clean_frame[y1:y2, x1:x2]
                            if tehdit_fotosu.size > 0:
                                dosya_adi = f"ihlaller/tehdit_id_{obj_id}.jpg"
                                cv2.imwrite(dosya_adi, tehdit_fotosu)
                                kaydedilen_idler.add(obj_id)
            
            canli_veri["tehditler"] = aktif_hedeler_bilgisi
                
        ret, buffer = cv2.imencode('.jpg', annotated_frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/veri_cek')
def veri_cek():
    return jsonify(canli_veri)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    print(">>> SİSTEM HAZIR! Tarayıcını aç ve şu adrese git: http://127.0.0.1:5000")
    app.run(debug=True, port=5000, use_reloader=False)