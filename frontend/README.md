# Smart Parking frontend

React, Vite, TypeScript, Tailwind CSS, React Router và TanStack Query. Giao diện dùng API FastAPI hiện có, không chứa khoá API hay thông tin đăng nhập cố định.

## Chạy trên Windows PowerShell

1. Chạy backend theo hướng dẫn ở README gốc. API mặc định tại `http://127.0.0.1:8000`.
2. Trong `frontend/`, chạy `Copy-Item .env.example .env` rồi `npm ci`.
3. Chạy `npm run dev` và mở URL Vite in ra. Vite chuyển tiếp `/api` tới backend cục bộ.
4. Đăng nhập bằng tài khoản Admin/Operator đã tạo theo hướng dẫn backend.

`VITE_API_BASE_URL` chỉ là đường dẫn API công khai (mặc định `/api/v1`), không phải chỗ lưu bí mật. Nếu triển khai khác nguồn, đặt biến này thành URL API và cấu hình CORS ở backend.

## Kiểm tra

```powershell
npm test
npm run lint
npm run format:check
npm run build
```

Trang Tổng quan lấy thống kê từ `/lots/current/occupancy`; khi chưa có ảnh, không tự tạo giá trị 0%. Trang Cấu hình hiển thị camera và vùng đỗ; thao tác chỉnh sửa hình học hiện dùng API quản trị. Trang Phân tích gửi ảnh tới `/snapshots/predict`; cần checkpoint AI đã cấu hình để nhận dự đoán thật. Lịch sử, CSV và duyệt kết quả dùng API hiện có. Phiên đăng nhập chỉ lưu trong bộ nhớ và tự hết hạn hoặc thoát khi API trả 401.
