# ĐẶC TẢ CHUẨN DỮ LIỆU TRUNG GIAN (AI-CAD INTERMEDIATE SCHEMA)

> **Mục đích:** Đặc tả cấu trúc dữ liệu JSON trung gian độc lập với định dạng đầu vào (PDF/Ảnh) và định dạng xuất ra (CAD DXF / Floorplanner JSON / 3D BIM).

---

## 1. Cấu trúc JSON cấp cao nhất (Root Schema)

```json
{
  "project_metadata": {
    "project_name": "Muntstraat 1 Renovation",
    "project_code": "26-1122",
    "address": "Muntstraat 1, 1621 GB Hoorn",
    "author": "HET VASTGOEDBUREAU Engineering",
    "scale_ratio": "1:100",
    "units": "mm",
    "created_at": "2026-11-23T09:30:00Z"
  },
  "floors": [
    {
      "floor_id": "floor_ground",
      "floor_name": "Begane grond",
      "elevation_peil": -50,
      "bounding_box": {
        "x_min": 0,
        "y_min": 0,
        "x_max": 6720,
        "y_max": 9260
      },
      "corners": [],
      "walls": [],
      "openings": [],
      "spaces": [],
      "dimensions": []
    }
  ]
}
```

---

## 2. Chi tiết các thành phần (Components)

### 2.1. Đỉnh nút (Corners / Vertices)
Đại diện cho các giao điểm của tường, có tọa độ thực tế tính bằng milimet ($mm$):

```json
{
  "id": "c1",
  "x": 0.0,
  "y": 0.0,
  "elevation": 0.0
}
```

### 2.2. Đoạn tường (Walls)
Đoạn tường nối giữa hai điểm góc (`corner_start_id` $\rightarrow$ `corner_end_id`):

```json
{
  "id": "w1",
  "corner_start_id": "c1",
  "corner_end_id": "c2",
  "wall_type": "exterior",        // "exterior" (tường ngoài), "interior" (tường ngăn), "bearing" (tường chịu lực)
  "thickness": 200,               // Độ dày tường tính bằng mm
  "height": 2800,                 // Chiều cao tường tính bằng mm
  "material": "brick",            // Vật liệu (nếu bóc tách được từ Renvooi)
  "fire_rating_minutes": 30       // Tiêu chuẩn chống cháy (WDBBO)
}
```

### 2.3. Lỗ mở: Cửa đi & Cửa sổ (Openings)
Nằm trên một bức tường cụ thể, có thông số vị trí và quy cách:

```json
{
  "id": "door_1",
  "type": "swing_door",           // "swing_door", "sliding_door", "window", "opening"
  "wall_id": "w1",
  "position_along_wall_mm": 1200, // Khoảng cách từ corner_start_id đến mép cửa
  "width": 950,                   // Bề rộng cửa (mm)
  "height": 2100,                 // Chiều cao cửa (mm)
  "swing_direction": "inward_right", // Hướng mở cánh: "inward_left", "inward_right", "outward_left", "outward_right"
  "material": "wood_ral_9010"     // Vật liệu từ bảng Renvooi
}
```

### 2.4. Không gian phòng (Spaces / Rooms)
Một phòng là một đa giác khép kín được bao quanh bởi các bức tường hoặc đường ranh giới ảo:

```json
{
  "id": "space_1",
  "name": "winkel",               // Tên phòng nguyên bản
  "name_vn": "Cửa hàng",          // Tên phòng dịch sang tiếng Việt
  "category": "commercial",       // "commercial", "living", "bedroom", "bathroom", "kitchen", "corridor"
  "nominal_area_m2": 56.73,       // Diện tích ghi chú trên bản vẽ
  "calculated_area_m2": 56.71,    // Diện tích tính toán thực tế từ đa giác
  "boundary_corner_ids": ["c1", "c2", "c3", "c4", "c5"], // Danh sách thứ tự các góc bao quanh phòng
  "elevation_offset_mm": -50      // Cao độ sàn so với PEIL
}
```

### 2.5. Kích thước gióng (Dimensions)
Lưu trữ các số đo thực tế đọc được để kiểm tra chéo (Cross-validation):

```json
{
  "id": "dim_1",
  "text": "6720",
  "value_mm": 6720,
  "orientation": "horizontal",
  "start_point": {"x": 0.0, "y": 0.0},
  "end_point": {"x": 6720.0, "y": 0.0}
}
```
