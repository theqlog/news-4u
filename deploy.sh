# deploy.sh
# description: deploy the services
# usage: ./deploy.sh

docker-compose --env-file .env  -f docker-compose.prod.yml up -d --build
# stop the services
# docker stop news-4u-backend
# docker stop news-4u-frontend
# docker rm news-4u-backend
# docker rm news-4u-frontend
# # build the images
# docker build -t news-4u-backend ./backend
# docker build --build-arg NEXT_PUBLIC_API_URL=/api -t news-4u-frontend ./frontend

# # run the containers
# docker run -d \
#   --name news-4u-backend \
#   -p 127.0.0.1:8000:8000 \
#   -v $(pwd)/backend:/app \
#   -v $(pwd)/backend/news_4u.db:/app/news_4u.db \
#   --env-file backend/.env \
#   --restart unless-stopped \
#   news-4u-backend

# # Commented out for now because the database is already initialized
# docker exec -it news-4u-backend python scripts/init_db.py

# docker run -d \
#   --name news-4u-frontend \
#   -p 127.0.0.1:3000:3000 \
#   -e NEXT_PUBLIC_API_URL=/api \
#   --restart unless-stopped \
#   news-4u-frontend