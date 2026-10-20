cmake_minimum_required(VERSION 3.5)
project(lift_ros)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

install(FILES README.md LICENSE DESTINATION share/${PROJECT_NAME})

ament_package()
