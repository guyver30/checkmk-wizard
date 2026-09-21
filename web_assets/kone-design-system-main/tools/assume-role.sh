SESSION_NAME="${CI_BUILD_ID}-$(date +%Y%m%d)"

unset AWS_ACCESS_KEY_ID; unset AWS_SECRET_ACCESS_KEY; unset AWS_SESSION_TOKEN;

echo "Assuming role $DEPLOY_ROLE_ARN..."
sts=$(
    aws sts assume-role \
    --role-arn "$DEPLOY_ROLE_ARN" \
    --role-session-name "$SESSION_NAME" \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text
)

export AWS_ACCESS_KEY_ID=$(echo "$sts" | awk '{print $1}')
export AWS_SECRET_ACCESS_KEY=$(echo "$sts" | awk '{print $2}')
export AWS_SESSION_TOKEN=$(echo "$sts" | awk '{print $3}')

echo "Role assumed successfully"
