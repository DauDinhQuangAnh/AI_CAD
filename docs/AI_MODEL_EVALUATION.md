# NGHIÊN CỨU VÀ ĐÁNH GIÁ CÁC MÔ HÌNH AI CHO BÀI TOÁN PHÂN TÍCH MẶT BẰNG KIẾN TRÚC (AI_CAD)

> **Mục tiêu:** Phân tích, so sánh chuyên sâu và định hình chiến lược lựa chọn mô hình AI (Model Selection Strategy) cho hệ thống tự động bóc tách bản vẽ 2D sang CAD / Floorplanner.  
> **Tác giả:** Dau Dinh Quang Anh  
> **Tài liệu tham chiếu:** [docs/ARCHITECTURE_AND_PLAN.md](ARCHITECTURE_AND_PLAN.md) | [docs/DATA_SCHEMA.md](DATA_SCHEMA.md)

---

## 1. TẠI SAO BÀI TOÁN KIẾN TRÚC ĐÒI HỎI CHIẾN LƯỢC ĐA MÔ HÌNH (MULTI-MODEL)?

Trong kỹ thuật kiến trúc xây dựng (AEC/CAD), độ chính xác tuyệt đối là yếu tố sống còn:
- Một bức tường vẽ lệch $20\text{ mm}$ có thể dẫn đến sai lệch kết cấu.
- Một con số kích thước bị đọc sai (ví dụ: `6720` đọc nhầm thành `6728`) sẽ làm sai lệch toàn bộ diện tích sàn.
- Các phòng phải là các đa giác khép kín ($Closed\ Polygons$) thì phần mềm vẽ sàn (Floorplanner, SketchUp) mới nhận diện được không gian.

Do đó, **không một mô hình AI đơn lẻ nào hiện nay có thể giải quyết toàn bộ bài toán từ đầu đến cuối**:
* **LLM (Large Language Models):** Cực kỳ thông minh trong việc đọc hiểu chữ, số kích thước, ngữ nghĩa phòng và quy chuẩn kỹ thuật, nhưng **yếu về đo lường tọa độ số học chính xác từng pixel** (hiện tượng ảo giác hình học - *Geometric Hallucination*).
* **Computer Vision (CV) & Computational Geometry:** Cực kỳ chính xác về tọa độ, đường thẳng song song, góc vuông $90^\circ$ và tính khép kín hình học, nhưng **không hiểu được ý nghĩa bản vẽ** (không biết đâu là phòng khách, đâu là tường chịu lực, đâu là đường gióng kích thước).

$\rightarrow$ **Kết luận kiến trúc:** Hệ thống phải áp dụng **Chiến lược lai 2 tầng (Two-Tier Hybrid Strategy)**:
1. **Tier 1 (Semantic Brain):** Multimodal Vision LLM đọc hiểu ngữ nghĩa & kích thước.
2. **Tier 2 (Geometric Skeleton):** Computer Vision / Geometry Engine trích xuất tọa độ & ràng buộc hình học.

---

## 2. ĐÁNH GIÁ CHI TIẾT CÁC MÔ HÌNH VISION LLM (MULTIMODAL AI)

Đây là các ứng viên đóng vai trò "Bộ não" đọc hiểu bản vẽ.

```
┌────────────────────────────────────────────────────────────────────────┐
│                   BẢNG TIÊU CHÍ ĐÁNH GIÁ (EVALUATION CRITERIA)          │
│ 1. Native High-Res OCR: Khả năng đọc chữ/số kỹ thuật kích thước siêu nhỏ│
│ 2. Spatial Reasoning: Hiểu mối quan hệ không gian (vị trí tương đối)   │
│ 3. Structured Output: Sinh JSON chuẩn xác theo JSON Schema / Pydantic  │
│ 4. Tốc độ suy luận (Latency) & Chi phí token (Cost efficiency)         │
│ 5. Khả năng triển khai Offline / On-premise (Bảo mật dữ liệu)          │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1. Google Gemini 2.0 Flash / Pro
- **Đặc tính kỹ thuật:** Hỗ trợ kích thước cửa sổ ngữ cảnh cực lớn (1M - 2M tokens), xử lý hình ảnh độ phân giải nguyên bản (Native High-Resolution Vision) mà không bị downscale gắt gao như các model khác.
- **Điểm mạnh đối với AI_CAD:**
  - Khả năng đọc OCR số đo kỹ thuật (ví dụ các số `< 6720 >`, `< 9260 >`, `-50 +PEIL`) trên bản vẽ cực kỳ chuẩn xác.
  - Tốc độ của **Gemini 2.0 Flash** siêu nhanh (thường dưới $1.2\text{ giây}$ cho một trang bản vẽ phức tạp).
  - Chi phí API thuộc nhóm rẻ nhất thị trường hiện nay (có hạn mức miễn phí hỗ trợ giai đoạn R&D).
  - Hỗ trợ chế độ Structured Output (ép kiểu JSON Schema) gần như tuyệt đối, không sinh text thừa ngoài JSON.
- **Hạn chế:** Cần prompt chặt chẽ để mô hình không tóm tắt quá ngắn những chi tiết kỹ thuật phức tạp trong bảng Renvooi.
- **Khuyến nghị:** ⭐️ **Mô hình chính (Primary Engine) cho toàn bộ hệ thống.**

---

### 2.2. Anthropic Claude 3.5 Sonnet
- **Đặc tính kỹ thuật:** Mô hình hàng đầu thế giới về tư duy logic, lập trình (Coding) và suy luận không gian thị giác (Visual Spatial Reasoning).
- **Điểm mạnh đối với AI_CAD:**
  - Nhận thức không gian xuất sắc: Rất giỏi phân tích mối liên hệ giữa các phòng (ví dụ: *"Phòng tắm nằm cạnh sảnh và ngăn cách với phòng ngủ bằng tường thạch cao"*).
  - Viết code thuật toán CAD và sinh mã vector SVG rất chuẩn.
- **Hạn chế:**
  - Chi phí API cao hơn đáng kể so với Gemini Flash ($3.00 / 1M input tokens$).
  - Có cơ chế nén ảnh nếu ảnh đầu vào vượt quá giới hạn pixel (cần phải cắt nhỏ ảnh trước khi gửi vào Claude).
- **Khuyến nghị:** Dùng làm **Mô hình thẩm định chuyên sâu (Deep Validation / Fallback Engine)** cho các bản vẽ cực kỳ phức tạp hoặc khi Gemini cần kiểm tra chéo.

---

### 2.3. OpenAI GPT-4o & GPT-4o-mini
- **Đặc tính kỹ thuật:** Mô hình đa phương thức toàn diện của OpenAI, hệ sinh thái SDK phong phú.
- **Điểm mạnh đối với AI_CAD:**
  - Hỗ trợ JSON Mode / Strict Structured Outputs rất ổn định.
  - Xử lý tốt đa ngôn ngữ (tiếng Hà Lan, Đức, Anh, Việt).
- **Hạn chế:**
  - Bản `GPT-4o-mini` khi gặp bản vẽ có mật độ nét dày đặc và số kích thước nhỏ dễ bị bỏ sót hoặc đọc nhầm số `1` thành `7`, số `3` thành `8`.
  - Bản `GPT-4o` lớn có chi phí tương đối cao.
- **Khuyến nghị:** Giữ vai trò **Mô hình dự phòng cấp 2 (Secondary Fallback)**.

---

### 2.4. Qwen2.5-VL (7B / 72B) & DeepSeek-VL (Mã nguồn mở / Open-Source)
- **Đặc tính kỹ thuật:** Các mô hình thị giác mã nguồn mở hàng đầu hiện nay, đặc biệt là **Qwen2.5-VL** (Alibaba Cloud) có khả năng định vị tọa độ vật thể ($Grounding\ / Bounding\ Box$) xuất sắc.
- **Điểm mạnh đối với AI_CAD:**
  - **Tự lưu trữ (Self-hosted / On-premise):** Khách hàng doanh nghiệp hoặc các đơn vị kiến trúc có yêu cầu bảo mật bản vẽ nội bộ (không muốn gửi dữ liệu lên Cloud API) có thể chạy hoàn toàn offline trên máy chủ riêng.
  - Bản **7B** có thể chạy mượt mà trên 1 GPU RTX 3090 / 4090 (24GB VRAM) bằng thư viện `vLLM` hoặc `Ollama`.
- **Hạn chế:** Cần đầu tư phần cứng GPU riêng và cấu hình hạ tầng triển khai.
- **Khuyến nghị:** Lựa chọn chiến lược cho **Phiên bản Doanh nghiệp (Enterprise On-Premise Edition)** trong tương lai.

---

## 3. BẢNG SO SÁNH MA TRẬN CÁC MÔ HÌNH MULTIMODAL LLM

| Tiêu chí | Gemini 2.0 Flash | Claude 3.5 Sonnet | GPT-4o | Qwen2.5-VL (72B) |
| :--- | :---: | :---: | :---: | :---: |
| **Độ nét OCR số kích thước nhỏ** | ⭐️⭐️⭐️⭐️⭐️ (Rất cao) | ⭐️⭐️⭐️⭐️ (Cao) | ⭐️⭐️⭐️⭐️ (Cao) | ⭐️⭐️⭐️⭐️ (Cao) |
| **Suy luận không gian phòng** | ⭐️⭐️⭐️⭐️ (Tốt) | ⭐️⭐️⭐️⭐️⭐️ (Xuất sắc) | ⭐️⭐️⭐️⭐️ (Tốt) | ⭐️⭐️⭐️⭐️ (Tốt) |
| **Tuân thủ JSON Schema** | ⭐️⭐️⭐️⭐️⭐️ (100%) | ⭐️⭐️⭐️⭐️⭐️ (100%) | ⭐️⭐️⭐️⭐️⭐️ (100%) | ⭐️⭐️⭐️⭐️ (Khá) |
| **Tốc độ xử lý (Latency)** | **< 1.2s** (Rất nhanh) | ~ 2.5s - 4s | ~ 2s - 3s | Tùy GPU (2s - 5s) |
| **Chi phí API / 1M token** | **Rẻ nhất** (~$0.10) | Cao (~$3.00) | Trung bình (~$2.50) | Miễn phí (tốn tiền GPU) |
| **Khả năng chạy Offline** | Không (Cloud API) | Không (Cloud API) | Không (Cloud API) | **Có (Self-hosted)** |
| **Vị trí đề xuất** | **Mô hình chính (Primary)** | **Thẩm định chéo (Reviewer)** | **Dự phòng (Fallback)** | **Bản On-premise** |

---

## 4. CÁC MÔ HÌNH COMPUTER VISION & ĐỒ HỌA CHUYÊN DỤNG (GEOMETRY & SEGMENTATION)

Đối với việc nhận diện hình học (tường, cửa, cửa sổ) trên ảnh scan raster (Sprint 4), các mô hình học sâu chuyên dụng sau được nghiên cứu áp dụng:

### 4.1. SAM 2 (Segment Anything Model 2 - Meta AI)
- **Ứng dụng trong AI_CAD:** Phân đoạn mặt nạ tường (*Wall Segmentation Mask*).
- **Cơ chế:** Đưa ảnh mặt bằng vào SAM 2 để trích xuất lớp mặt nạ (binary mask) của toàn bộ hệ tường đen. Sau đó dùng thuật toán `Skeletonize / Medial Axis Transform` để tìm đường tim tường.
- **Ưu điểm:** Khả năng bắt nét chuẩn xác từng pixel, xử lý tốt cả bản vẽ vẽ tay hoặc scan bị nhòe mực.

### 4.2. YOLOv11-OBB (Oriented Bounding Box - Ultralytics)
- **Ứng dụng trong AI_CAD:** Nhận diện ký hiệu kiến trúc xoay góc:
  - Cửa đi cánh mở (*Swing Door*) kèm góc xoay và hướng mở.
  - Cửa sổ (*Window*).
  - Cầu thang (*Stairs*).
  - Thiết bị vệ sinh (*Toilet, Sink, Bathtub*).
- **Ưu điểm:** Tốc độ suy luận siêu tốc ($5 - 15\text{ ms}$ trên CPU/GPU), kích thước model siêu nhẹ (~$20\text{ MB}$).

### 4.3. CubiCasa5k & Raster-to-Graph (Mô hình học thuật chuyên sâu)
- **Ứng dụng trong AI_CAD:** Tham khảo kiến trúc mô hình từ bộ dữ liệu mở **CubiCasa5k** (chuyên chuẩn hóa hơn 5.000 bản vẽ nhà ở châu Âu).
- **Cơ chế:** Biến ảnh bản vẽ trực tiếp thành đồ thị các điểm nút (*Junctions*) và liên kết (*Wall Edges*).

---

## 5. THỰC NGHIỆM ĐIỂM CHỨNG TRÊN FILE MẪU `test1.pdf`

Dự án đã tiến hành thử nghiệm bóc tách thực tế trên tập dữ liệu mẫu `data/raw/test1.pdf` (Bản vẽ công trình Muntstraat 1, Hoorn, Hà Lan):

```
┌────────────────────────────────────────────────────────────────────────┐
│              KẾT QUẢ KIỂM CHỨNG BÓC TÁCH (BENCHMARK RESULTS)           │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Text Layer Vector Extraction (PyMuPDF):                             │
│    - Số block text nhận diện: 104 / 104 block (100% chính xác)         │
│    - Tên phòng: winkel (56,73 m²), entree (13,37 m²),                  │
│                 woonkamer/keuken (34,58 m²), badkamer (9,55 m²),       │
│                 slaapkamer (10,45 m²)...                               │
│    - Kích thước đo: 6720 mm, 9260 mm, 5773 mm, 3448 mm, 3500 mm...     │
│    - Độ trễ trích xuất vector: 0.045 giây                              │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Cắt cúp & Chuẩn hóa vùng vẽ (Region Cropping):                      │
│    - Vùng nội dung thực: Rect(1190, 1000, 2385, 1684)                  │
│    - Giảm 74.3% diện tích thừa (khoảng trắng vô ích)                   │
│    - Tăng độ phân giải hữu ích cho Vision LLM lên gấp 4 lần.           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 6. CHIẾN LƯỢC TRIỂN KHAI TRONG MÃ NGUỒN (CODE INTEGRATION STRATEGY)

Để đảm bảo tính linh hoạt, hệ thống sẽ sử dụng mẫu thiết kế **Provider Pattern / Strategy Pattern** thông qua class trừu tượng `BaseVisionLLM`:

```python
# Cấu trúc mã nguồn module LLM (src/llm/base.py)
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseVisionLLM(ABC):
    """Lớp cơ sở trừu tượng cho tất cả các Vision LLM Provider."""
    
    @abstractmethod
    def parse_dimensions(self, image_path: str, context_text: str) -> Dict[str, Any]:
        """Bóc tách các chuỗi kích thước và hướng gióng."""
        pass

    @abstractmethod
    def classify_rooms(self, image_path: str, room_polygons: list) -> Dict[str, Any]:
        """Gán nhãn tên phòng, công năng và đối chiếu diện tích."""
        pass
```

Các provider cụ thể sẽ được hiện thực:
- `GeminiVisionProvider` (`src/llm/gemini_provider.py`): Sử dụng SDK `google-genai`.
- `ClaudeVisionProvider` (`src/llm/claude_provider.py`): Sử dụng SDK `anthropic`.
- `OpenAIVisionProvider` (`src/llm/openai_provider.py`): Sử dụng SDK `openai`.

---

## 7. KẾT LUẬN & ĐỀ XUẤT HÀNH ĐỘNG

1. **Giai đoạn hiện tại (Sprint 1 - 3):**
   - Sử dụng **Toán hình học thuần túy (PyMuPDF + Shapely)** cho các file PDF vector để có độ chính xác $100\%$ và chi phí $0$ đồng.
   - Sử dụng **Gemini 2.0 Flash** làm mô hình LLM chính để bóc tách ngữ nghĩa, chuỗi kích thước và quy chuẩn vật liệu.
2. **Giai đoạn hoàn thiện (Sprint 4):**
   - Huấn luyện nhẹ **YOLOv11-OBB** trên tập dữ liệu ký hiệu cửa/cửa sổ để xử lý ảnh scan raster.
   - Thử nghiệm đóng gói **Qwen2.5-VL-7B** phục vụ chế độ chạy cục bộ (Offline Mode).
