# Auto IPV4 start (useful for mobile device testing)

$env:getIp = ipconfig
if ($env:getIp -match '(IPv4[\sa-zA-Z.]+:\s[0-9.]+)') {
    if ($matches[1] -match '([^a-z\s][\d]+[.\d]+)'){
        $ipv4 = $matches[1]
    }
}
echo $ipv4