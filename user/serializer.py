from rest_framework import serializers
from .models import CustomUser
from django.contrib.auth.password_validation import validate_password
import random


class UserRegistrationSerializers(serializers.ModelSerializer):
    password = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField( write_only=True)
    username = serializers.CharField(required=False)

    class Meta:
        model = CustomUser
        fields = ["first_name","last_name","email_address","username","phone_number","username","password","confirm_password", "roles"] 

    def validate_email_address(self, value):
        if CustomUser.objects.filter(email_address=value).exists():
            raise serializers.ValidationError("Email Address already exists")
        if "@" not in value:
            raise serializers.ValidationError("Invalid Email Address")
        return value
    

    def validate(self, attrs):
        # 1. FIX: raise the error, don't return it
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"password": "Passwords don't match."})
        
        # 2. Validate password strength
        validate_password(attrs['password'])

        # 3. FIX: Generate username here if it's missing
        if not attrs.get('username'):
            first_name = attrs.get('first_name', 'user').lower()
            random_num = random.randint(1000, 9999)
            generated_username = f"{first_name}{random_num}"

            # Ensure uniqueness
            while CustomUser.objects.filter(username=generated_username).exists():
                generated_username = f"{first_name}{random.randint(1000, 99999)}"
            
            attrs['username'] = generated_username

        return attrs
    
    # username_number = random.randint(0,100)
    # print (username_number)

    # def validate_username(self, validated_data):
    #     if "username" not in validated_data:
    #         validated_data["username"] = validated_data.get("first_name","") + validated_data.get("first_name","") + str("username_number")

    # def create(self, validated_data, values):
    #     validated_data.pop("confirm_password")

    #     if CustomUser.objects.filter(username=values).exists():

    #     return super().create(validated_data)
    
    
    def create(self, validated_data):
        validated_data.pop("confirm_password")

        user = CustomUser.objects.create_user(**validated_data)

        # user = CustomUser.objects.create_user(
        #     first_name=validated_data["first_name"],
        #     last_name=validated_data["last_name"],
        #     email_address=validated_data["email_address"],
        #     phone_number=validated_data["phone_number"],
        #     username=validated_data["username"],
        #     password=validated_data["password"],
        # )

        return user

class UserLoginSerializer(serializers.Serializer):
    email_address = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class EmailOTP(serializers.Serializer):
    email_address = serializers.EmailField()
    email_otp = serializers.CharField(required=False, max_length = 6)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'email_address', 'username', 'phone_number', 'roles','created_at']

class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Restricted serializer for self-service profile edits.
    Deliberately excludes id, email_address, roles, password, created_at,
    updated_at, email_verified — none of those should change through a
    generic PUT/PATCH.
    """
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'username', 'phone_number']